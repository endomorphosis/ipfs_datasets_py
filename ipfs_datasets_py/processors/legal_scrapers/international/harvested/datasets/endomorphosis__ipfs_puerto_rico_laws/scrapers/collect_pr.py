#!/usr/bin/env python3
"""Puerto Rico: OGP Biblioteca Virtual (Leyes Orgánicas / Leyes de Referencia) +
Departamento de Estado Órdenes Ejecutivas (docs.pr.gov) + Constitution.

Official-only *.pr.gov / *.gov.pr / oslpr.org (SUTRA enacted Ley PDFs).
Live SharePoint FileRef catalogs + CDX of the same official URLs.
NOT lexjuris.com / vLex / commercial aggregators.
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

CC, COUNTRY, LANG = "pr", "Puerto Rico", "es"
SOURCE_TYPE = "bvirtual_ogp_pr"
LICENSE = (
    "Gobierno de Puerto Rico / Estado Libre Asociado — Oficina de Gerencia y "
    "Presupuesto Biblioteca Virtual (bvirtualogp.pr.gov); Departamento de Estado "
    "(docs.pr.gov Órdenes Ejecutivas); Oficina de Servicios Legislativos (sutra.oslpr.org "
    "enacted Ley PDFs). Compilaciones OGP facilitan lectura; texto auténtico de la "
    "ley original / L.P.R.A. / Gaceta prevalece. Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://bvirtualogp.pr.gov/)"
)
# Spanish civil-law drafting + English bilingual mirrors
ART = re.compile(
    r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO|Article|Section|"
    r"Secci[oó]n|SCHEDULE|Schedule|Cap[ií]tulo|CHAPTER)\s+[0-9]+[A-Za-zº°.]?)\b"
)
log = logging.getLogger("pr")
MAX_PDF = env_int("MAX_PDF_BYTES", 12 * 1024 * 1024)

HOST_OK = (
    "bvirtualogp.pr.gov",
    "ogp.pr.gov",
    "www.ogp.pr.gov",
    "docs.pr.gov",
    "estado.pr.gov",
    "www.estado.pr.gov",
    "presupuesto.pr.gov",
    "www.presupuesto.pr.gov",
    "sutra.oslpr.org",
    "www.oslpr.org",
    "oslpr.org",
    "senado.pr.gov",
    "www.senado.pr.gov",
)
SKIP_RE = re.compile(
    r"(lexjuris|vlex|powerpoint|pptx|agenda|newsletter|brochure|"
    r"favicon|holder__|vacancy|tender|questionnaire|pasaporte|ds11|ds82|ds3053|"
    r"\bbill\b|proyecto.?de.?ley|borrador|draft-|draft_|memorial.?explicativo|"
    r"carta.?circular|cartas.?circulares|cartasnormativas|ogp_cc|"
    r"/6-plan/|/3-duplicados/|/3a-triplicada/|"
    r"informe|votacion|votaci[oó]n|entirillado|prontuario|"
    r"user-manual|ayuda|"
    r"CEUA\.pdf|"  # US Constitution (not PR)
    r"\.docx?$|\.jpe?g$|\.png$|\.doc$)",
    re.I,
)
KEEP_RE = re.compile(
    r"(ley|leyes|constituc|organica|org[aá]nica|orden.?ejecutiva|\bOE[-_ ]?\d|"
    r"reglamento|resoluci[oó]n.?conjunta|\bRC\b|c[oó]digo|estatuto|"
    r"/Bvirtual/|/leyesreferencia/|/LeyesOrganicas/|"
    r"/OrdenesEjecutivas/|/SutraFilesGen/|Ley%20|Ley\s+\d|"
    r"Derechos%20Civiles|Derechos Civiles|/CONST/|CONST\.pdf)",
    re.I,
)
CDX_PREFIXES = (
    "bvirtualogp.pr.gov/ogp/Bvirtual/leyesreferencia/PDF/",
    "bvirtualogp.pr.gov/ogp/Bvirtual/LeyesOrganicas/PDF/",
    "bvirtualogp.pr.gov/ogp/Bvirtual/LeyesOrganicas/pdf/",
    "bvirtualogp.pr.gov/ogp/Bvirtual/LeyesOrganicas/Pages/",
    "docs.pr.gov/files/Estado/OrdenesEjecutivas/",
    "docs.pr.gov/files/OIG/Biblioteca%20Virtual/Constituciones/",
    "docs.pr.gov/files/OGP/",
)
SEED_DOCS = (
    (
        "https://bvirtualogp.pr.gov/ogp/Bvirtual/leyesreferencia/PDF/"
        "Derechos%20Civiles/CONST/CONST.pdf",
        "Constitución del Estado Libre Asociado de Puerto Rico",
        "CONSTITUTION",
    ),
    (
        "https://docs.pr.gov/files/OIG/Biblioteca%20Virtual/Constituciones/"
        "Constituci%C3%B3n%20del%20Estado%20Libre%20Asociado%20de%20Puerto%20Rico.pdf",
        "Constitución del Estado Libre Asociado de Puerto Rico (OIG)",
        "CONSTITUTION",
    ),
    (
        "https://bvirtualogp.pr.gov/ogp/Bvirtual/LeyesOrganicas/pdf/147-1980.pdf",
        "Ley Orgánica de la Oficina de Gerencia y Presupuesto 147-1980",
        "ORGANICA",
    ),
    (
        "https://bvirtualogp.pr.gov/ogp/Bvirtual/leyesreferencia/PDF/129-2020.pdf",
        "Ley de Condominios de Puerto Rico 129-2020",
        "LEY",
    ),
    (
        "https://bvirtualogp.pr.gov/ogp/Bvirtual/leyesreferencia/PDF/83-2025.pdf",
        "Ley de la Policía de Puerto Rico 83-2025",
        "LEY",
    ),
)
LIVE_PAGES = (
    "https://bvirtualogp.pr.gov/ogp/Bvirtual/LeyesOrganicas/Pages/main_view.aspx",
    "https://bvirtualogp.pr.gov/ogp/Bvirtual/leyesreferencia/Pages/main_view.aspx",
    "https://www.estado.pr.gov/ordenes-ejecutivas",
    "https://estado.pr.gov/ordenes-ejecutivas",
    "https://bvirtualogp.pr.gov/ogp/Bvirtual/Pages/default.aspx",
    "https://www.ogp.pr.gov/",
)
OE_YEARS = tuple(range(2026, 2012, -1))
# Prefer thematic shelves over bulk /2/ pads and English mirrors
THEMATIC_HINT = re.compile(
    r"/(Derechos%20Civiles|Derechos Civiles|Justicia|Salud|Educaci|"
    r"Trabajo|Agricultura|Ambientales|Municipios|Turismo|Incentivos|"
    r"Arte%20y%20Cultura|Arte y Cultura|Recursos|Telecomunicaciones|"
    r"Registro|Presupuesto|Constitucion|Constituci|"
    r"Y%20-%20Ingl|Y - Ingl)/",
    re.I,
)


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if not url:
        return url
    # drop utm / cache busters on PDFs
    if "?" in url and ".pdf" in url.lower():
        url = url.split("?")[0]
    host = (urlparse(url).hostname or "").lower()
    if host.endswith(".pr.gov") or host.endswith(".gov.pr") or host.endswith("oslpr.org"):
        url = url.replace("http://", "https://").replace(":80/", "/")
    # Prefer canonical LeyesOrganicas/pdf/ over Pages/ when both appear
    if "/LeyesOrganicas/Pages/" in url and url.lower().endswith(".pdf"):
        url = url.replace("/LeyesOrganicas/Pages/", "/LeyesOrganicas/pdf/")
    # normalize PDF vs pdf path segment case for leyesreferencia
    url = url.replace("/leyesreferencia/pdf/", "/leyesreferencia/PDF/")
    # Percent-encode spaces / unsafe path chars from CDX
    try:
        parts = urlparse(url)
        if parts.path and ((" " in parts.path) or any(ord(c) < 33 for c in parts.path)):
            segs = parts.path.split("/")
            enc = "/".join(quote(unquote(s), safe=".-_()%~") for s in segs)
            url = parts._replace(path=enc).geturl()
    except Exception:
        pass
    return url


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if any(h == host or host.endswith("." + h) for h in HOST_OK):
        return True
    return host.endswith(".pr.gov") or host.endswith(".gov.pr") or host.endswith("oslpr.org")


def _category(url: str, hint: str = "") -> str:
    blob = f"{url} {hint}".lower()
    if "constituc" in blob or "/const/" in blob or "const.pdf" in blob:
        if "ceua" in blob or "estados unidos de america" in blob:
            return ""  # skip US constitution
        return "CONSTITUTION"
    if "leyesorganicas" in blob or "orgánica" in blob or "organica" in blob:
        return "ORGANICA"
    if re.search(r"orden.?ejecutiva|\boe[-_ /]?\d|/ordenesejecutivas/", blob):
        return "OE"
    if re.search(r"resoluci[oó]n.?conjunta|/4-rc/|\brc\b", blob):
        return "RC"
    if re.search(r"reglamento", blob):
        return "REGLAMENTO"
    if re.search(r"\bley\b|/leyesreferencia/|ley%20n|ley_n[uú]m", blob):
        return "LEY"
    return ""


def _ident_from_url(url: str, hint: str = "") -> str:
    path = unquote(urlparse(url).path)
    stem = Path(path).stem
    # Prefer ley number pattern NNN-YYYY
    m = re.search(r"(\d{1,4}-\d{4}[a-zA-Z]?)", stem) or re.search(
        r"(\d{1,4}-\d{4}[a-zA-Z]?)", path
    )
    if m:
        prefix = "organica" if "leyesorganicas" in path.lower() else "ley"
        if "ordenesejecutivas" in path.lower() or re.search(r"\bOE\b", stem, re.I):
            prefix = "oe"
        if "const" in stem.lower() or "constituc" in path.lower():
            prefix = "constitution"
        return f"{prefix}_{m.group(1)}"[:160]
    if re.search(r"constituc|/\bCONST\b", path, re.I) or stem.upper() == "CONST":
        return "constitution_ela_pr"
    if hint:
        h = re.sub(r"[^\w.\-]+", "_", hint).strip("_")[:160]
        if h and len(h) > 6:
            return h
    # OE stems
    m = re.search(r"(OE[-_ ]?\d{4}[-_ ]?\d+)", stem, re.I)
    if m:
        return re.sub(r"[^\w.\-]+", "_", m.group(1))[:160]
    return (stem or "doc")[:160]


def _rank(ident: str, cat: str, url: str) -> int:
    blob = f"{ident} {cat} {url}".lower()
    if cat == "CONSTITUTION" or "constitution" in blob or "/const/" in blob:
        return 0
    # Recent / root consolidations before bulk orgánicas so MAX_NEW gets mix
    year_m = re.search(r"(20[12]\d|19\d\d)", unquote(urlparse(url).path))
    year = int(year_m.group(1)) if year_m else 0
    is_root = bool(re.search(r"/leyesreferencia/PDF/[^/]+\.pdf$", url, re.I))
    is_them = bool(THEMATIC_HINT.search(url)) and "ingles" not in blob and "ingl" not in blob
    if (is_root or is_them) and year >= 2015 and "ingles" not in blob:
        return 1
    if cat == "ORGANICA" or "leyesorganicas" in blob:
        return 2
    if is_them:
        return 3
    if is_root:
        return 4
    if cat == "LEY" and "/2/" not in blob and "ingles" not in blob:
        return 5
    if cat == "LEY":
        return 6
    if cat == "RC":
        return 7
    if cat == "OE" or "/ordenesejecutivas/" in blob:
        return 8
    if cat == "REGLAMENTO":
        return 9
    if "ingles" in blob or "ingl" in blob or "2-ingles" in blob:
        return 10
    return 11

def _session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
            "Accept-Language": "es-PR,es;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    )
    sess.verify = False
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    return sess


def _extract_filerefs(html: str) -> list[str]:
    """SharePoint CSR embeds FileRef as unicode-escaped JSON fragments."""
    refs = re.findall(r"FileRef\\u0022:\\u0022([^\\]+)\\u0022", html)
    if not refs:
        refs = re.findall(r'"FileRef"\s*:\s*"([^"]+)"', html)
    out = []
    for r in refs:
        path = r.replace("\\u002f", "/").replace("\\/", "/")
        # unescape leftover \\u00xx sequences
        try:
            path = path.encode("utf-8").decode("unicode_escape")
        except Exception:
            pass
        path = unquote(path)
        if path.lower().endswith(".pdf"):
            out.append(path)
    return out


def discover():
    items, seen_url, best = [], set(), {}

    def add(url, ts="", title_hint="", cat=""):
        url = _norm(url)
        if not url or " " in url.split("://", 1)[-1].split("/", 1)[0]:
            return
        low = url.lower()
        if ".pdf" not in low:
            return
        if not _host_ok(url):
            return
        # hard skip commercial
        if "lexjuris" in low or "vlex.com" in low:
            return
        blob = f"{low} {title_hint} {cat}"
        if SKIP_RE.search(blob):
            return
        if not KEEP_RE.search(blob):
            return
        cat = cat or _category(url, title_hint)
        if not cat and "ceua" in low:
            return
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

    sess = _session()

    # --- OGP Biblioteca Virtual SharePoint catalogs ---
    for page in LIVE_PAGES[:2]:
        try:
            gr = sess.get(page, timeout=120)
            if gr.status_code != 200:
                log.warning("bvirtual page %s status=%s", page, gr.status_code)
                continue
            before = len(best)
            for path in _extract_filerefs(gr.text):
                if not path.startswith("/"):
                    continue
                full = "https://bvirtualogp.pr.gov" + path
                tip = Path(unquote(urlparse(full).path)).stem.replace("_", " ")[:200]
                add(full, "", tip, _category(full, tip))
            # also bare .pdf hrefs
            for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', gr.text, re.I):
                full = urljoin(gr.url, href)
                if _host_ok(full):
                    tip = Path(unquote(urlparse(full).path)).stem.replace("_", " ")[:200]
                    add(full, "", tip)
            log.info("bvirtual %s +%s catalog=%s", page.split("/")[-3], len(best) - before, len(best))
        except Exception as exc:
            log.warning("bvirtual %s fail: %s", page, exc)

    # --- Departamento de Estado Órdenes Ejecutivas (docs.pr.gov) ---
    for year in OE_YEARS:
        page = f"https://www.estado.pr.gov/ordenes-ejecutivas?year={year}"
        try:
            gr = sess.get(page, timeout=45)
            if gr.status_code != 200:
                continue
            before = len(best)
            for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', gr.text, re.I):
                full = urljoin(gr.url, href)
                if "ordenesejecutivas" not in full.lower() and "OrdenesEjecutivas" not in full:
                    if "docs.pr.gov" not in full:
                        continue
                tip = Path(unquote(urlparse(full).path)).stem.replace("%20", " ")[:200]
                add(full, "", tip, "OE")
            log.info("OE year=%s +%s catalog=%s", year, len(best) - before, len(best))
        except Exception as exc:
            log.warning("OE year=%s fail: %s", year, exc)

    # homepage / ogp seeds
    for page in LIVE_PAGES[2:]:
        try:
            gr = sess.get(page, timeout=45)
            if gr.status_code != 200:
                continue
            for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', gr.text, re.I):
                full = urljoin(gr.url, href)
                tip = Path(unquote(urlparse(full).path)).stem.replace("_", " ")[:200]
                add(full, "", tip)
        except Exception as exc:
            log.warning("live %s fail: %s", page, exc)

    # --- Light SUTRA enacted-law sample (Ley Núm. PDFs only; skip bill dossiers) ---
    try:
        su = sess.get("https://sutra.oslpr.org/", timeout=45)
        if su.status_code == 200:
            for href in re.findall(r'href=["\']([^"\']*prontuarios/leyes-aprobadas/\d+)["\']', su.text, re.I):
                full = urljoin(su.url, href)
                try:
                    lr = sess.get(full, timeout=40)
                    if lr.status_code != 200:
                        continue
                    for href2, tip in re.findall(
                        r'<a[^>]+href=["\']([^"\']+\.pdf[^"\']*)["\'][^>]*>(.*?)</a>',
                        lr.text,
                        re.I | re.S,
                    ):
                        tip_c = re.sub(r"<[^>]+>", "", tip).strip()
                        if not re.search(r"Ley\s+N[uú]m", tip_c, re.I):
                            continue
                        pdf = urljoin(lr.url, href2)
                        add(pdf, "", tip_c[:200], "LEY")
                except Exception:
                    continue
    except Exception as exc:
        log.warning("sutra fail: %s", exc)

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
    # Prefer Spanish; fall back to spa+eng for bilingual texts
    text, how, pages = extract_pdf_text(
        raw, enable_ocr=True, ocr_lang="spa", ocr_max_pages=ocr_pages
    )
    if text and len(text) >= 100:
        return text, how, pages
    return extract_pdf_text(
        raw, enable_ocr=True, ocr_lang="spa+eng", ocr_max_pages=ocr_pages
    )


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
        if not title or title.startswith("printery_"):
            for line in text.splitlines():
                if len(line.strip()) > 18:
                    title = line.strip()[:240]
                    break
        if cat and title and cat.lower() not in title.lower():
            title = f"{title} [{cat}]"
        # language hint: bilingual possible
        lang = LANG
        sample = (text or "")[:4000].lower()
        if sample.count(" the ") > 30 and sample.count(" el ") + sample.count(" la ") < 10:
            lang = "en"
        if save_instrument(
            cc=CC, country=COUNTRY, language=lang, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_pr.py",
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
            "OGP Biblioteca Virtual (bvirtualogp.pr.gov) / Departamento de Estado "
            "Órdenes Ejecutivas (docs.pr.gov) / OSL SUTRA enacted Ley PDFs"
        ),
        source_urls=[
            "https://bvirtualogp.pr.gov/ogp/Bvirtual/Pages/default.aspx",
            "https://bvirtualogp.pr.gov/ogp/Bvirtual/LeyesOrganicas/Pages/main_view.aspx",
            "https://bvirtualogp.pr.gov/ogp/Bvirtual/leyesreferencia/Pages/main_view.aspx",
            "https://www.estado.pr.gov/ordenes-ejecutivas",
            "https://docs.pr.gov/files/Estado/OrdenesEjecutivas/",
            "https://sutra.oslpr.org/",
            "https://www.ogp.pr.gov/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (OGP Leyes Orgánicas + Leyes de Referencia "
            "SharePoint FileRefs + docs.pr.gov OE + CDX; SUTRA Ley Núm. PDFs)"
        ),
        notes=(
            f"Official bvirtualogp.pr.gov consolidations (Leyes Orgánicas / Referencia) + "
            f"CONST.pdf + docs.pr.gov Estado OrdenesEjecutivas + sutra.oslpr.org enacted "
            f"Ley Núm. PDFs; live-first + Wayback CDX. Prefer Constitution + Orgánicas + "
            f"thematic leyes + OEs. OCR spa/spa+eng used={ocr_used}. Skip lexjuris/vLex/"
            f"bills/cartas circulares/CEUA(US). Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
