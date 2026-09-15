#!/usr/bin/env python3
"""Cuba: official Gaceta Oficial + Ministerio de Justicia PDFs (lean leyes/códigos).

Official only:
  https://www.gacetaoficial.gob.cu/
  https://www.minjus.gob.cu/
No vLex / La Ley. Prefer substantive leyes/códigos/constitución; cap gazette shells.
Live TLS on gacetaoficial often 403; prefer live then Wayback of the same official URL.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
import urllib.parse
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "cu", "Cuba", "es"
SOURCE_TYPE = "gaceta_oficial_cu"
LICENSE = (
    "Gaceta Oficial / Ministerio de Justicia de la República de Cuba "
    "(gacetaoficial.gob.cu, minjus.gob.cu). Authentic official text prevails. Not legal advice."
)
UA = (
    "legal-corpora-collector/1.0 "
    "(research; sources=https://www.gacetaoficial.gob.cu/ https://www.minjus.gob.cu/)"
)
# Allow letter suffixes (Artículo 12 bis / 12A)
ART = re.compile(
    r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s+[\d]+[A-Za-zº°o.]?)\b"
)
log = logging.getLogger("cu")

OFFICIAL_HOSTS = (
    "gacetaoficial.gob.cu",
    "www.gacetaoficial.gob.cu",
    "minjus.gob.cu",
    "www.minjus.gob.cu",
)

SKIP_NAME = re.compile(
    r"(?i)("
    r"trimestre|índice|indice|referativo|pandemia|brochure|afiche|folleto|"
    r"cronograma|anteproyecto|nota\s*introduct|prontuario|autorizaci|"
    r"relaci[oó]n\s*mipymes|boletin|gu[ií]a\s*telef|compilacion|"
    r"revista_juridica|rev\._juridica|justicia\s*360|intervenci[oó]n|"
    r"mipymes|quiros|participacion_del_ministerio|derecho\s*registral|"
    r"proyecto\s+de\s+(ley|c[oó]digo)|eliminaci[oó]n\s+de\s+trabas"
    r")"
)
LEAN_NAME = re.compile(
    r"(?i)("
    r"ley[_\s-]|codigo|c[oó]digo|constituci|decreto[_-]?ley|dl[\s_-]?\d|"
    r"codigo_|ley\d|reglamento"
    r")"
)
GOC_NAME = re.compile(r"(?i)(^|/)(goc-|gaceta)")


def _norm_url(url: str) -> str:
    url = (url or "").strip().split("#")[0].split("?")[0]
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith("http"):
        url = "https://" + url.lstrip("/")
    url = re.sub(r"https://([^/]+):80/", r"https://\1/", url)
    url = re.sub(r"http://([^/]+):80/", r"http://\1/", url)
    url = url.replace("http://www.gacetaoficial.gob.cu/", "https://www.gacetaoficial.gob.cu/")
    url = url.replace("http://gacetaoficial.gob.cu/", "https://www.gacetaoficial.gob.cu/")
    url = url.replace("https://gacetaoficial.gob.cu/", "https://www.gacetaoficial.gob.cu/")
    url = url.replace("http://www.minjus.gob.cu/", "https://www.minjus.gob.cu/")
    url = url.replace("http://minjus.gob.cu/", "https://www.minjus.gob.cu/")
    url = url.replace("https://minjus.gob.cu/", "https://www.minjus.gob.cu/")
    url = re.sub(r"(https://www\.gacetaoficial\.gob\.cu)/+", r"\1/", url)
    url = re.sub(r"(https://www\.minjus\.gob\.cu)/+", r"\1/", url)
    return url


def _is_official_pdf(url: str) -> bool:
    low = url.lower()
    if ".pdf" not in low:
        return False
    if not any(h in low for h in ("gacetaoficial.gob.cu", "minjus.gob.cu")):
        return False
    if any(x in low for x in (".jpg", ".png", "favicon", "/theme/", "/user/", "wp-content")):
        return False
    return True


def _file_ident(url: str) -> str:
    name = unquote(Path(urlparse(url).path).name)
    stem = Path(name).stem if name.lower().endswith(".pdf") else name
    stem = stem.strip()[:160]
    if not stem:
        stem = re.sub(r"\W+", "-", url)[-100:]
    return stem


def _live_minjus_normas() -> list[str]:
    """Scrape Ministerio Justicia normas_juridicas page for PDF hrefs."""
    import urllib.request

    url = "https://www.minjus.gob.cu/es/publicaciones/normas_juridicas"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception as exc:
        log.info("minjus normas live fail: %s", exc)
        return []
    found = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', html, re.I):
        full = urllib.parse.urljoin("https://www.minjus.gob.cu", href)
        if ".pdf" in full.lower() and "minjus.gob.cu" in full.lower():
            found.append(_norm_url(full))
    log.info("minjus normas live pdfs %s", len(set(found)))
    return sorted(set(found))


def discover() -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    seen: set[str] = set()
    cdx_limit = env_int("CDX_LIMIT", 500)
    max_goc = env_int("MAX_GOC_SHELLS", 40)  # cap gazette issue shells

    def add(url: str) -> None:
        url = _norm_url(url)
        if not _is_official_pdf(url):
            return
        name = unquote(Path(urlparse(url).path).name)
        if SKIP_NAME.search(name):
            return
        key = re.sub(r"^https?://(www\.)?", "", url.lower()).rstrip("/")
        if key in seen:
            return
        seen.add(key)
        items.append((_file_ident(url), url))

    # 1) Live Minjus normas (lean priority source)
    for u in _live_minjus_normas():
        add(u)

    # 2) CDX: prefer minjus publicacion + marco-legal, then gaceta /pdf/ GOC issues
    prefixes = [
        ("www.minjus.gob.cu/sites/default/files/archivos/publicacion/", cdx_limit),
        ("www.minjus.gob.cu/sites/default/files/archivos/marco-legal/", max(80, cdx_limit // 4)),
        ("www.gacetaoficial.gob.cu/pdf/", cdx_limit),
        ("gacetaoficial.gob.cu/pdf/", max(120, cdx_limit // 3)),
        ("www.gacetaoficial.gob.cu/sites/default/files/", max(80, cdx_limit // 4)),
    ]
    for prefix, lim in prefixes:
        for h in cdx_urls(
            prefix,
            limit=lim,
            match_type="prefix",
            extra_filters=["mimetype:application/pdf"],
        ):
            orig = h.get("original") or ""
            if orig:
                add(orig)

    lean: list[tuple[str, str]] = []
    goc: list[tuple[str, str]] = []
    other: list[tuple[str, str]] = []
    for ident, url in items:
        blob = (ident + " " + url).lower()
        if LEAN_NAME.search(ident) or LEAN_NAME.search(url):
            lean.append((ident, url))
        elif GOC_NAME.search(ident) or "/pdf/goc-" in blob:
            goc.append((ident, url))
        else:
            other.append((ident, url))

    def rank_lean(it: tuple[str, str]):
        ident, url = it
        low = (ident + " " + url).lower()
        score = 0
        if "constituci" in low:
            score -= 100
        if "codigo" in low or "código" in low or "c%c3%b3digo" in low:
            score -= 80
        if re.search(r"ley[_\s-]?\d|ley_", low):
            score -= 60
        if "decreto" in low or re.search(r"\bdl\b", low):
            score -= 40
        if "minjus" in low:
            score -= 20
        if "proyecto" in low or "anteproyecto" in low:
            score += 80
        return (score, ident)

    lean.sort(key=rank_lean)
    # Cap gazette shells; keep most recent-looking GOC first
    def rank_goc(it: tuple[str, str]):
        ident = it[0]
        m = re.search(r"(20\d{2}|19\d{2})", ident)
        year = int(m.group(1)) if m else 0
        return (-year, ident)

    goc.sort(key=rank_goc)
    goc = goc[:max_goc]
    # Drop non-lean other noise (revistas, etc.) — already filtered by SKIP, keep small
    other = [it for it in other if LEAN_NAME.search(it[0])][:20]

    ordered = lean + other + goc
    # de-dupe again preserving order
    out: list[tuple[str, str]] = []
    seen2: set[str] = set()
    for ident, url in ordered:
        key = re.sub(r"^https?://(www\.)?", "", url.lower()).rstrip("/")
        if key in seen2:
            continue
        seen2.add(key)
        out.append((ident, url))
    log.info(
        "catalog %s (lean=%s goc_capped=%s other=%s raw=%s)",
        len(out),
        len(lean),
        len(goc),
        len(other),
        len(items),
    )
    return out


def seed_done_from_hub(done: set[str]) -> int:
    seed = Path(ROOT) / CC / "_hub_seed_ids.json"
    if not seed.exists():
        return 0
    try:
        ids = json.loads(seed.read_text(encoding="utf-8"))
        n0 = len(done)
        for i in ids:
            done.add(str(i))
            done.add(slug_id(CC, str(i)))
        return len(done) - n0
    except Exception as exc:
        log.info("hub seed fail %s", exc)
        return 0


def _title_from_text(text: str, ident: str) -> str:
    skip_pfx = (
        "gaceta oficial",
        "de la república de cuba",
        "de la republica de cuba",
        "edición:",
        "edicion:",
        "ministerio de justicia",
        "corrección:",
        "composici",
        "diseño de cubierta",
        "todos los derechos",
        "www.",
        "http",
    )
    for line in text.splitlines():
        s = line.strip()
        if len(s) < 12:
            continue
        low = s.lower()
        if any(low.startswith(p) for p in skip_pfx):
            continue
        if low in ("cuba", "la habana", "extraordinaria", "ordinaria"):
            continue
        if re.fullmatch(r"[\d./\-]+", s):
            continue
        return s[:240]
    # fallback: humanize ident
    return unquote(ident).replace("_", " ")[:240]


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 100)
    max_seconds = env_int("MAX_SECONDS", 4500)
    t_start = time.time()
    done = existing_ids(CC)
    seeded = seed_done_from_hub(done)
    if seeded:
        log.info("seeded %s hub ids (done=%s)", seeded, len(done))
    ok = skip = fail = 0
    catalog = discover()
    for ident, url in catalog:
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        alt = slug_id(CC, urllib.parse.quote(ident, safe=""))
        # also skip if stem already present under different host encoding
        if rid in done or alt in done or ident in done:
            skip += 1
            continue
        # disk guard
        try:
            import shutil as _sh

            free_g = _sh.disk_usage(str(ROOT)).free / (1024**3)
            if free_g < 8.0:
                log.warning("disk free %.1fG < 8G — stopping", free_g)
                break
        except Exception:
            pass
        got = fetch_official(url, ua=UA, verify=False, min_text=150)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        # skip oversized scan shells (> ~2.5M chars of thin gazette) unless lean-named
        if len(text) > 2_500_000 and not LEAN_NAME.search(ident):
            fail += 1
            log_failure(
                CC,
                {
                    "identifier": ident,
                    "source_url": url,
                    "reason": f"oversized_nonlean_chars={len(text)}",
                },
            )
            continue
        host = urlparse(url).netloc.lower()
        st = "minjus_cu" if "minjus" in host else SOURCE_TYPE
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=_title_from_text(text, ident),
            text=text,
            source_url=url,
            source_type=st,
            license_text=LICENSE,
            collector="collect_cu.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method"), "source_host": host},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC,
        country=COUNTRY,
        source="Gaceta Oficial / Ministerio de Justicia de Cuba",
        source_urls=[
            "https://www.gacetaoficial.gob.cu/",
            "https://www.minjus.gob.cu/es/publicaciones/normas_juridicas",
        ],
        license_text=LICENSE,
        discovered=len(catalog),
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="catalog-backed incomplete (official Minjus leyes/códigos + capped Gaceta PDFs)",
        notes=(
            "Lean deepen: prefer leyes/códigos from minjus.gob.cu; cap GOC gazette shells. "
            "Official only. Not vLex. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
