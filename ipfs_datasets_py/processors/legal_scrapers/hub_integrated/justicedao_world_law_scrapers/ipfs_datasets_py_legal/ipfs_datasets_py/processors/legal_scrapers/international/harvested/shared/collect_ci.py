#!/usr/bin/env python3
"""Côte d'Ivoire: official law PDFs from Assemblée nationale (assnat.ci) + SGG (sgg.gouv.ci).

Official only:
  - https://assnat.ci/ IMG/pdf lois + constitution (live text PDFs)
  - https://www.sgg.gouv.ci/ documentheque photo_doc (often image-only scans; OCR fra)
  - Wayback/CDX of the same official hosts when live fails

JO at sgg.gouv.ci/jo.php is login-gated (download code) — skipped.
Not AfricanLII. No WAF bypass. Not legal advice.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse, quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import (
    cdx_urls,
    env_int,
    fetch_official,
    live_get,
    pdf_to_text,
    save_instrument,
    setup_log,
    slug_id,
)

CC, COUNTRY, LANG = "ci", "Côte d'Ivoire", "fr"
SOURCE_TYPE = "jo_cotedivoire"
LICENSE = (
    "Secrétariat Général du Gouvernement (sgg.gouv.ci) / Assemblée nationale "
    "(assnat.ci). Authentic Journal Officiel / official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.sgg.gouv.ci/)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.)\s+\d+[a-zA-Z]?)\b")
log = logging.getLogger("ci")

KEEP_RE = re.compile(
    r"(constitution|loi|code|ordonnance|reglement|r[eè]glement|decret|d[eé]cret)",
    re.I,
)
DROP_RE = re.compile(
    r"(calendrier|commission|annuaire|liste[_-]?des[_-]?depute|leparlementaire|"
    r"groupe[_-]?parlementaire|depute|session[_-]?ordinaire|octobre20\d{2}-|"
    r"memotextes|memo[_-]?des)",
    re.I,
)
SGG_KEEP_RE = re.compile(
    r"(loi|decret|d[eé]cret|ordonnance|code|regl|r[eè]gl|constitution|circulaire)",
    re.I,
)

# Live-working assnat IMG/pdf seeds (prefer these over legacy assembleenationale paths)
SEED_ASSNAT = [
    "https://assnat.ci/IMG/pdf/constitution_de_la_republique_de_cote_d_ivoireloi_-_no_2016-886_du_08_novembre_2016.pdf",
    "https://assnat.ci/reglement-assembleenationaledecotedivoire.pdf",
    "https://assnat.ci/IMG/pdf/loi_portant_code_penal.pdf",
    "https://assnat.ci/IMG/pdf/loi_code_forestier.pdf",
    "https://assnat.ci/IMG/pdf/loi_relative_a_l_adoption.pdf",
    "https://assnat.ci/IMG/pdf/loi_relative_au_mariage.pdf",
    "https://assnat.ci/IMG/pdf/loi_relative_aux_successions.pdf",
    "https://assnat.ci/IMG/pdf/loi_relative_a_la_filiation.pdf",
    "https://assnat.ci/IMG/pdf/loi_relative_a_la_minorite.pdf",
    "https://assnat.ci/IMG/pdf/loi_reforme_hospitaliere.pdf",
    "https://assnat.ci/IMG/pdf/loi_relative_au_code_de_la_construction.pdf",
    "https://assnat.ci/IMG/pdf/loi_service_civique.pdf",
    "https://assnat.ci/IMG/pdf/loi_representation_de_la_femme_assemblees_elues.pdf",
    "https://assnat.ci/IMG/pdf/loi_sur_la_metrologie.pdf",
    "https://assnat.ci/IMG/pdf/loi_antitabac.pdf",
    "https://assnat.ci/IMG/pdf/loi_cei.pdf",
    "https://assnat.ci/IMG/pdf/loi_cni_biometrique.pdf",
    "https://assnat.ci/IMG/pdf/loi_modificative_foncier_rural.pdf",
    "https://assnat.ci/IMG/pdf/loi_d_orientation_politique_de_sante_publique.pdf",
]

# SGG photo_doc (often scanned; OCR when needed)
SEED_SGG = [
    "https://www.sgg.gouv.ci/photo_doc/1343063229Loi%2078-662%20Magistrature.PDF",
    "https://www.sgg.gouv.ci/photo_doc/1343063311Loi%2095-553%20Code%20minier.PDF",
    "https://www.sgg.gouv.ci/photo_doc/1343063986Loi%2092-570%20Fonction%20publique.PDF",
    "https://www.sgg.gouv.ci/photo_doc/1343215842Loi%202000-514%20Code%20Electoral.pdf",
    "https://www.sgg.gouv.ci/photo_doc/Loi_2000_513.pdf",
    "https://www.sgg.gouv.ci/photo_doc/134321796898-388.PDF",
    "https://www.sgg.gouv.ci/photo_doc/13432188312011-481%20Cafe%20Cacao.pdf",
    "https://www.sgg.gouv.ci/photo_doc/13432192152011-270%20MPTIC.pdf",
    "https://www.sgg.gouv.ci/photo_doc/13432384142009-385%20Regl%20banque.PDF",
    "https://www.sgg.gouv.ci/photo_doc/1374057456Ordonnance-N-2012-487.pdf",
    "https://www.sgg.gouv.ci/photo_doc/1374057547Ordonnance_N_2012-158.pdf",
    "https://www.sgg.gouv.ci/photo_doc/1374057686Ordonnance_portant.pdf",
    "https://www.sgg.gouv.ci/photo_doc/1399281993Ordonnance_N_2013_481_du_02_juillet_2013.pdf",
    "https://www.sgg.gouv.ci/photo_doc/1399281952Decret_N_2013_279_du_24_avril_2013.pdf",
    "https://www.sgg.gouv.ci/photo_doc/1399281753Decret_N_2013_711_du_18_octobre_2013.pdf",
    "https://www.sgg.gouv.ci/photo_doc/1399281803Decret_N_2012_980_du_10_octobre_2012.pdf",
    "https://www.sgg.gouv.ci/photo_doc/1373646863Decret_N_2012-867.pdf",
    "https://www.sgg.gouv.ci/photo_doc/1373646924Decret%20N_2012-652.pdf",
    "https://www.sgg.gouv.ci/photo_doc/1373647016Decret%20N_2012-365.pdf",
]


def _norm_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip().replace(":80/", "/")
    if url.startswith("http://www.sgg.gouv.ci/"):
        url = "https://" + url[len("http://") :]
    elif url.startswith("http://sgg.gouv.ci/"):
        url = "https://www." + url[len("http://") :]
    elif url.startswith("http://www.assnat.ci/"):
        url = "https://" + url[len("http://") :]
    elif url.startswith("http://assnat.ci/"):
        url = "https://" + url[len("http://") :]
    # Prefer bare assnat.ci IMG paths (live) over www.assnat.ci/assembleenationale legacy
    if "assnat.ci/assembleenationale/IMG/pdf/" in url:
        url = url.replace("www.assnat.ci/assembleenationale/IMG/pdf/", "assnat.ci/IMG/pdf/")
        url = url.replace("assnat.ci/assembleenationale/IMG/pdf/", "assnat.ci/IMG/pdf/")
    try:
        p = urlparse(url)
        parts = []
        for seg in p.path.split("/"):
            if not seg:
                parts.append(seg)
                continue
            parts.append(seg if "%" in seg else quote(seg, safe="._-"))
        url = p._replace(path="/".join(parts), params="", query="", fragment="").geturl()
    except Exception:
        url = url.replace(" ", "%20")
    return url


def _ident_from_url(url: str) -> str:
    name = unquote(Path(urlparse(url).path).name)
    stem = Path(name).stem
    return re.sub(r"\W+", "-", stem).strip("-")[:160] or re.sub(r"\W+", "-", url)[-80:]


def _title_from_url(url: str) -> str:
    name = unquote(Path(urlparse(url).path).name)
    stem = Path(name).stem
    stem = re.sub(r"^\d{10}", "", stem).strip(" _-")
    return stem.replace("_", " ").replace("%20", " ")[:240] or stem


def _add(items, seen, ident, url, meta=None):
    url = _norm_url(url)
    if not url or url in seen:
        return
    if ".pdf" not in url.lower():
        return
    seen.add(url)
    ident = re.sub(r"\W+", "-", (ident or _ident_from_url(url)).strip("-"))[:160]
    items.append((ident, url, meta or {}))


def _assnat_ok(url: str) -> bool:
    path = unquote(urlparse(url).path)
    low = path.lower()
    if DROP_RE.search(low):
        return False
    return bool(KEEP_RE.search(low))


def _sgg_ok(url: str) -> bool:
    name = unquote(Path(urlparse(url).path).name)
    if SGG_KEEP_RE.search(name):
        return True
    if re.match(r"^\d{10}\.pdf$", name, re.I):
        return True
    return "photo_doc" in url.lower() and name.lower().endswith(".pdf")


def ocr_pdf(raw: bytes) -> str:
    """French OCR for image-only SGG ScanSnap PDFs."""
    max_pages = env_int("MAX_OCR_PAGES", 30)
    dpi = env_int("OCR_DPI", 150)
    try:
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "doc.pdf"
            pdf.write_bytes(raw)
            proc = subprocess.run(
                ["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(Path(td) / "p")],
                check=False,
                capture_output=True,
                timeout=240,
            )
            if proc.returncode != 0:
                log.warning("pdftoppm: %s", (proc.stderr or b"")[:200])
                return ""
            pages = sorted(Path(td).glob("p*.png"))
            chunks = []
            for img in pages[:max_pages]:
                tproc = subprocess.run(
                    ["tesseract", str(img), "stdout", "-l", "fra", "--psm", "6"],
                    check=False,
                    capture_output=True,
                    timeout=120,
                )
                if tproc.returncode == 0 and tproc.stdout:
                    chunks.append(tproc.stdout.decode("utf-8", "replace").strip())
            return "\n\n".join(c for c in chunks if c).strip()
    except Exception as exc:
        log.warning("ocr_pdf: %s", exc)
        return ""


def fetch_ci(url: str, *, wayback_ts=None, allow_ocr: bool = True) -> dict:
    """fetch_official then OCR image-only PDFs when needed."""
    got = fetch_official(url, ua=UA, verify=False, min_text=120, wayback=True, wayback_ts=wayback_ts)
    if got.get("status") == "success":
        return got
    # Try alternate assnat path forms before OCR
    alts = []
    if "assnat.ci/IMG/pdf/" in url:
        alts.append(url.replace("https://assnat.ci/IMG/pdf/", "https://www.assnat.ci/assembleenationale/IMG/pdf/"))
        alts.append(url.replace("https://assnat.ci/IMG/pdf/", "http://www.assnat.ci/assembleenationale/IMG/pdf/"))
    elif "assembleenationale/IMG/pdf/" in url:
        alts.append(re.sub(r"https?://(?:www\.)?assnat\.ci/assembleenationale/IMG/pdf/", "https://assnat.ci/IMG/pdf/", url))
    for alt in alts:
        if alt == url:
            continue
        got2 = fetch_official(alt, ua=UA, verify=False, min_text=120, wayback=True)
        if got2.get("status") == "success":
            got2["pdf_url_used"] = alt
            return got2
    # OCR path: download PDF bytes then OCR
    if not allow_ocr:
        return got
    body = got.get("content") or b""
    if not (isinstance(body, bytes) and body[:4] == b"%PDF"):
        try:
            r = live_get(url, ua=UA, verify=False, timeout=(20, 90), retries=2)
            body = r.content or b""
        except Exception as exc:
            got["error"] = (got.get("error") or "") + f";ocr_dl:{exc}"
            return got
    if not (isinstance(body, bytes) and body[:4] == b"%PDF"):
        return got
    max_ocr_bytes = env_int("MAX_OCR_BYTES", 8 * 1024 * 1024)
    if len(body) > max_ocr_bytes:
        got["error"] = (got.get("error") or "") + f";ocr_skip_too_large:{len(body)}"
        return got
    # Prefer pdftotext again; if form-feeds only, OCR
    text = pdf_to_text(body)
    text_clean = re.sub(r"[\x0c\s]+", "", text or "")
    if len(text_clean) >= 120:
        got.update(status="success", text=text, content=body, method="http_pdf")
        return got
    log.info("OCR fra %s bytes=%s", url.split("/")[-1][:60], len(body))
    ocr = ocr_pdf(body)
    if len(ocr) >= 120:
        got.update(status="success", text=ocr, content=body, method="http_pdf_ocr_fra")
        return got
    got["error"] = (got.get("error") or "") + ";ocr_short"
    return got


def discover_seeds(items, seen):
    for url in SEED_ASSNAT:
        if _assnat_ok(url):
            _add(items, seen, _ident_from_url(url), url, {"portal": "assnat.ci_seed", "title": _title_from_url(url)})
    for url in SEED_SGG:
        _add(items, seen, _ident_from_url(url), url, {"portal": "sgg.gouv.ci_seed", "title": _title_from_url(url)})


def discover_assnat_lois(items, seen):
    """Paginate assnat.ci ?-lois-82- and resolve attached IMG/pdf links."""
    base = "https://assnat.ci/"
    pages = []
    page_seen = set()
    max_pages = env_int("ASSNAT_LOIS_PAGES", 14)
    for i in range(max_pages):
        debut = i * 12
        url = f"{base}?-lois-82-" if debut == 0 else f"{base}?-lois-82-&debut_articles={debut}"
        try:
            r = live_get(url, ua=UA, verify=False, timeout=(15, 45), retries=2)
        except Exception as exc:
            log.info("assnat lois list fail debut=%s: %s", debut, exc)
            break
        found = 0
        for href in re.findall(r'href=["\'](\./?\?[^"\']+)["\']', r.text or ""):
            full = urljoin(base, href.replace("&amp;", "&"))
            low = full.lower()
            if not any(k in low for k in ("?loi-", "?code-", "?constitution", "loi-", "code-")):
                continue
            if any(k in low for k in ("projet-de-loi", "proposition-de-loi", "lois-82", "communiques")):
                continue
            if full in page_seen:
                continue
            page_seen.add(full)
            pages.append(full)
            found += 1
        log.info("assnat lois debut=%s found=%s catalog_pages=%s", debut, found, len(pages))
        if found == 0 and i > 0:
            break

    # Also constitution + code electoral index pages
    for extra in (f"{base}?-la-constitution-", f"{base}?-le-code-electoral-"):
        if extra not in page_seen:
            pages.insert(0, extra)

    resolve_n = env_int("ASSNAT_RESOLVE", 80)
    for page_url in pages[:resolve_n]:
        try:
            r = live_get(page_url, ua=UA, verify=False, timeout=(12, 40), retries=1)
        except Exception as exc:
            log.info("assnat resolve fail %s: %s", page_url[:80], exc)
            continue
        title_m = re.search(r"<title[^>]*>(.*?)</title>", r.text or "", re.I | re.S)
        page_title = (title_m.group(1).strip().split("|")[0].strip() if title_m else "")[:240]
        # Prefer H1/widget title if present
        h = re.search(
            r'<(?:h[1-4]|div)[^>]*class="[^"]*(?:entry-title|widget-title|title)[^"]*"[^>]*>\s*([^<]{8,200})',
            r.text or "",
            re.I,
        )
        if h:
            page_title = h.group(1).strip()[:240] or page_title
        for href in re.findall(r'(?:href|src)=["\']([^"\']+\.pdf[^"\']*)["\']', r.text or "", re.I):
            full = urljoin(page_url, href)
            if "assnat.ci" not in full.lower():
                continue
            if not _assnat_ok(full):
                continue
            _add(
                items,
                seen,
                _ident_from_url(full),
                full,
                {
                    "portal": "assnat.ci_lois",
                    "title": page_title or _title_from_url(full),
                    "page_url": page_url,
                },
            )


def discover_sgg_live(items, seen):
    base = "https://www.sgg.gouv.ci/"
    for cas in (2, 3, 4):
        empty = 0
        for depart in range(0, 120, 15):
            seed = urljoin(base, f"documentheque.php?id_cas={cas}&depart={depart}&c=s")
            try:
                r = live_get(seed, ua=UA, verify=False, timeout=(12, 35), retries=1)
            except Exception as exc:
                log.info("sgg live fail %s: %s", seed[:70], exc)
                break
            new = 0
            for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', r.text or "", re.I):
                full = urljoin(seed, href)
                if "photo_doc" not in full.lower():
                    continue
                if not _sgg_ok(full):
                    continue
                before = len(seen)
                _add(
                    items,
                    seen,
                    _ident_from_url(full),
                    full,
                    {"portal": "sgg.gouv.ci_live", "title": _title_from_url(full), "page_url": seed},
                )
                if len(seen) > before:
                    new += 1
            log.info("sgg cas=%s depart=%s new=%s total=%s", cas, depart, new, len(items))
            if new == 0:
                empty += 1
                if empty >= 2 or depart == 0:
                    break
            else:
                empty = 0


def _cdx_with_retry(prefix: str, limit: int, retries: int = 3) -> list[dict]:
    for attempt in range(1, retries + 1):
        try:
            hits = cdx_urls(
                prefix,
                limit=limit,
                match_type="prefix",
                extra_filters=["mimetype:application/pdf"],
            )
            return hits or []
        except Exception as exc:
            log.info("cdx retry %s attempt=%s: %s", prefix, attempt, exc)
            time.sleep(min(10, 2 * attempt))
    return []


def discover_cdx(items, seen):
    if env_int("SKIP_CDX", 0):
        log.info("SKIP_CDX=1 — skipping Wayback CDX discovery")
        return
    limit = env_int("CDX_LIMIT", 120)
    for prefix in (
        "assnat.ci/IMG/pdf/",
        "www.assnat.ci/assembleenationale/IMG/pdf/",
        "www.sgg.gouv.ci/photo_doc/",
    ):
        hits = _cdx_with_retry(prefix, limit=limit)
        log.info("cdx %s hits=%s", prefix, len(hits))
        for h in hits:
            orig = (h.get("original") or "").strip()
            if not orig or ".pdf" not in orig.lower():
                continue
            if "sgg.gouv" in orig and not _sgg_ok(orig):
                continue
            if "assnat.ci" in orig and not _assnat_ok(orig):
                continue
            portal = "sgg.gouv.ci_cdx" if "sgg.gouv" in orig else "assnat.ci_cdx"
            _add(
                items,
                seen,
                _ident_from_url(orig),
                orig,
                {"portal": portal, "title": _title_from_url(orig), "cdx_ts": h.get("timestamp")},
            )


def discover():
    items, seen = [], set()
    discover_seeds(items, seen)
    seed_n = len(items)
    discover_assnat_lois(items, seen)
    discover_sgg_live(items, seen)
    live_n = len(items) - seed_n
    discover_cdx(items, seen)
    log.info("catalog total=%s (seeds=%s live_added~%s)", len(items), seed_n, live_n)

    def rank(it):
        ident, url, meta = it
        t = ((meta.get("title") or "") + " " + url).lower()
        portal = meta.get("portal") or ""
        score = 0
        if "constitution" in t:
            score -= 200
        if "assnat" in portal and "seed" in portal:
            score -= 80
        if "assnat.ci_lois" in portal:
            score -= 70
        if "code_penal" in t or "code penal" in t:
            score -= 60
        if "loi" in t or "code" in t:
            score -= 50
        if "ordonnance" in t:
            score -= 30
        if "decret" in t or "décret" in t:
            score -= 10
        if "sgg" in portal:
            score += 5  # prefer text PDFs from assnat before OCR-heavy SGG
        if "budget" in t or "finances" in t or "reglement_2018" in t:
            score += 20
        return (score, url)

    items.sort(key=rank)
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 60)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    portals: dict[str, int] = {}
    methods: dict[str, int] = {}
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
        # OCR mainly for SGG scans; assnat text PDFs usually don't need it
        allow_ocr = "sgg" in portal or env_int("OCR_ALL", 0) == 1
        got = fetch_ci(url, wayback_ts=meta.get("cdx_ts"), allow_ocr=allow_ocr)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(
                CC,
                {"identifier": ident, "source_url": url, "reason": got.get("error"), "portal": portal},
            )
            continue
        title = (meta.get("title") or "").strip() or next(
            (ln.strip()[:240] for ln in text.splitlines() if len(ln.strip()) > 18),
            ident,
        )
        # Prefer first substantive law-like line for title when page title is site chrome
        if title.lower().startswith("assemblée") or len(title) < 12:
            for ln in text.splitlines():
                s = ln.strip()
                if len(s) > 20 and re.search(r"(?i)\b(loi|constitution|ordonnance|décret|decret|code)\b", s):
                    title = s[:240]
                    break
        date = None
        m = re.search(r"(20\d{2}|19\d{2})[-_/ ](\d{1,2})[-_/ ](\d{1,2})", title + " " + ident)
        if m:
            date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        else:
            m2 = re.search(r"\b(20\d{2}|19\d{2})\b", title + " " + unquote(url))
            if m2:
                date = f"{m2.group(1)}-01-01"
        method = got.get("method") or ""
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title,
            text=text,
            source_url=meta.get("page_url") or got.get("pdf_url_used") or url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_ci.py",
            date=date,
            article_re=ART,
            extra_meta={
                "fetch_method": method,
                "portal": portal,
                "pdf_url": got.get("pdf_url_used") or url,
                "retrieval": "archive" if "wayback" in method else "live",
            },
        ):
            ok += 1
            done.add(rid)
            portals[portal] = portals.get(portal, 0) + 1
            methods[method] = methods.get(method, 0) + 1
            log.info("ok %s portal=%s chars=%s method=%s", ident[:70], portal, len(text), method)
        else:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "save_failed_short", "portal": portal})

    write_summary(
        CC,
        country=COUNTRY,
        source="SGG Côte d'Ivoire / Assemblée nationale",
        source_urls=[
            "https://assnat.ci/?-lois-82-",
            "https://assnat.ci/IMG/pdf/",
            "https://www.sgg.gouv.ci/documentheque.php?id_cas=2",
            "https://www.sgg.gouv.ci/photo_doc/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "thin-or-better official-hosted snapshot: assnat.ci IMG/pdf lois+constitution "
            "(live text PDFs) + sgg.gouv.ci photo_doc (OCR fra for scans). "
            "JO login wall skipped. Incomplete vs full JO corpus."
        ),
        notes=f"Official CI only. portals={portals} methods={methods}. Not AfricanLII. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s portals=%s methods=%s", ok, skip, fail, portals, methods)


if __name__ == "__main__":
    main()
