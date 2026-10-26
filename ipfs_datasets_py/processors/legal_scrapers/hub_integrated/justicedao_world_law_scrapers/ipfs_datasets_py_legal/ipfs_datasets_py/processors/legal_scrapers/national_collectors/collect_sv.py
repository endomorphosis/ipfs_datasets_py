#!/usr/bin/env python3
"""El Salvador: Asamblea Legislativa decree PDFs + Diario Oficial API gazettes."""
from __future__ import annotations
import json
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import (
    cdx_urls,
    env_int,
    fetch_official,
    first_title,
    live_get,
    save_instrument,
    setup_log,
    slug_id,
)

CC, COUNTRY, LANG = "sv", "El Salvador", "es"
SOURCE_TYPE = "asamblea_diario_oficial_sv"
LICENSE = (
    "Asamblea Legislativa / Diario Oficial de El Salvador "
    "(asamblea.gob.sv / diariooficial.gob.sv / imprentanacional.gob.sv). "
    "Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.diariooficial.gob.sv/)"
ART = re.compile(r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s+[\d]+[º°o.]?)\b")
log = logging.getLogger("sv")

ASAMBLEA = "https://www.asamblea.gob.sv"
DIARIO_API = "https://www.diariooficial.gob.sv/api/v1"
DIARIO_DOC = "https://www.diariooficial.gob.sv"
SKIP_PDF_HINTS = ("aviso", "subasta", "licitacion", "cotizacion")


def _ident_from_url(url: str, fallback: str) -> str:
    stem = Path(unquote(url.split("?")[0])).stem
    stem = re.sub(r"\s+", "-", stem).strip("-")[:140]
    return stem or fallback[:140]


def discover():
    """Return list of (ident, url, title_hint, prefer). Prefer Asamblea decree PDFs."""
    items, seen = [], set()

    def add(url: str, *, ident: str | None = None, title: str | None = None, prefer: bool = False):
        url = (url or "").split("#")[0]
        if not url.startswith("http"):
            return
        low = url.lower()
        if ".pdf" not in low and "/seleccion/" not in low:
            return
        if any(h in low for h in SKIP_PDF_HINTS):
            return
        # Official hosts only
        if not any(
            h in low
            for h in (
                "asamblea.gob.sv",
                "diariooficial.gob.sv",
                "imprentanacional.gob.sv",
            )
        ):
            return
        key = url.lower()
        if key in seen:
            return
        seen.add(key)
        iid = ident or _ident_from_url(url, "doc")
        items.append((iid, url, title, prefer))

    # --- Asamblea: year listings -> decree view pages -> documents/decretos PDFs ---
    years = list(range(env_int("SV_YEAR_START", 2018), env_int("SV_YEAR_END", 2027)))
    years.sort(reverse=True)
    view_ids: list[str] = []
    for year in years:
        list_url = f"{ASAMBLEA}/leyes-y-decretos/decretos-por-anios/{year}/0"
        try:
            r = live_get(list_url, ua=UA, verify=False, retries=2)
        except Exception as exc:
            log.info("asamblea list fail %s: %s", list_url, exc)
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        html = r.text or ""
        found = sorted(set(re.findall(r"/leyes-y-decretos/view/(\d+)", html)))
        # drop shared nav node 244 if many others present
        if len(found) > 10 and "244" in found:
            found = [x for x in found if x != "244"]
        log.info("asamblea %s views=%s", year, len(found))
        view_ids.extend(found)
        if len(view_ids) >= env_int("SV_MAX_VIEWS", 400):
            break

    # Dedup views preserving order
    seen_v = set()
    ordered_views = []
    for vid in view_ids:
        if vid in seen_v:
            continue
        seen_v.add(vid)
        ordered_views.append(vid)

    for vid in ordered_views[: env_int("SV_MAX_VIEWS", 400)]:
        vurl = f"{ASAMBLEA}/leyes-y-decretos/view/{vid}"
        try:
            r = live_get(vurl, ua=UA, verify=False, retries=1, timeout=(15, 45))
        except Exception as exc:
            log.info("view fail %s: %s", vid, exc)
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        html = r.text or ""
        title = None
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
        if m:
            title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            title = re.sub(r"\s+", " ", title)[:240]
        pdfs = sorted(
            set(
                re.findall(
                    r"https?://[^\"'\s]+/sites/default/files/documents/decretos/[^\"'\s]+\.pdf"
                    r"|/sites/default/files/documents/decretos/[^\"'\s]+\.pdf",
                    html,
                    re.I,
                )
            )
        )
        # also constitution / year-folder PDFs on decree-ish pages
        if not pdfs:
            pdfs = [
                p
                for p in sorted(
                    set(re.findall(r"https?://[^\"'\s]+\.pdf|/sites/default/files/[^\"'\s]+\.pdf", html, re.I))
                )
                if "documents/decretos" in p.lower()
                or re.search(r"/20\d{2}-\d{2}/", p)
                or "constituci" in p.lower()
            ]
        for href in pdfs:
            full = urljoin(ASAMBLEA + "/", href)
            if any(h in full.lower() for h in SKIP_PDF_HINTS):
                continue
            add(
                full,
                ident=f"dec-{vid}-{_ident_from_url(full, vid)}",
                title=title,
                prefer=True,
            )

    # Constitution page
    try:
        r = live_get(f"{ASAMBLEA}/leyes-y-decretos/constitucion", ua=UA, verify=False, retries=1)
        if getattr(r, "status_code", 0) == 200:
            for href in re.findall(r'href="([^"]+\.pdf)"', r.text or "", re.I):
                full = urljoin(ASAMBLEA + "/", href)
                if "aviso" not in full.lower():
                    add(full, ident=_ident_from_url(full, "constitucion"), title="Constitución de la República", prefer=True)
    except Exception as exc:
        log.info("constitucion fail: %s", exc)

    # --- Diario Oficial official API: year/month -> seleccion/{Id} PDFs ---
    do_years = list(range(env_int("DO_YEAR_START", 2022), env_int("DO_YEAR_END", 2027)))
    do_years.sort(reverse=True)
    for year in do_years:
        for month in range(1, 13):
            try:
                import requests
                from requests.packages.urllib3.exceptions import InsecureRequestWarning

                requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
                resp = requests.post(
                    f"{DIARIO_API}/diarios-disponibles",
                    data={"year": str(year), "month": str(month)},
                    headers={"User-Agent": UA},
                    timeout=(20, 60),
                    verify=False,
                )
            except Exception as exc:
                log.info("diario api %s-%s: %s", year, month, exc)
                continue
            if resp.status_code != 200:
                continue
            try:
                rows = resp.json()
            except Exception:
                continue
            if not isinstance(rows, list):
                continue
            log.info("diario %s-%02d n=%s", year, month, len(rows))
            for row in rows:
                rid = str(row.get("Id") or "").strip()
                if not rid:
                    continue
                nombre = (row.get("NombreArchivo") or f"{rid}.pdf").replace(".pdf", "")
                fecha = row.get("FechaInicio") or ""
                url = f"{DIARIO_DOC}/seleccion/{rid}"
                add(
                    url,
                    ident=f"do-{nombre}-{rid}",
                    title=f"Diario Oficial {fecha or nombre}",
                    prefer=False,
                )
            if sum(1 for *_, prefer in items if not prefer) >= env_int("SV_MAX_DIARIO", 120):
                break
        if sum(1 for *_, prefer in items if not prefer) >= env_int("SV_MAX_DIARIO", 120):
            break

    # CDX fallback for Asamblea decree PDFs
    for prefix in (
        "www.asamblea.gob.sv/sites/default/files/documents/decretos/",
        "asamblea.gob.sv/sites/default/files/documents/decretos/",
    ):
        for h in cdx_urls(
            prefix,
            limit=env_int("CDX_LIMIT", 150),
            match_type="prefix",
            extra_filters=["mimetype:application/pdf"],
        ):
            orig = (h.get("original") or "").replace("http://", "https://").replace(":80/", "/")
            if orig:
                add(orig, prefer=True)

    items.sort(key=lambda x: (0 if x[3] else 1, x[1]))
    out = [(i, u, t) for i, u, t, _ in items]
    log.info("catalog %s", len(out))
    return out


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 3600)
    min_text = env_int("MIN_TEXT", 200)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for ident, url, title_hint in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, verify=False, min_text=min_text)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        # Skip near-empty OCR shells
        if len(re.sub(r"\s+", "", text)) < 120:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "thin_ocr_shell"})
            continue
        title = title_hint or first_title(text, ident)
        # Prefer Asamblea-ish titles over garbled OCR headers
        if title_hint and len(title_hint) > 20:
            title = title_hint
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title,
            text=text,
            source_url=url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_sv.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC,
        country=COUNTRY,
        source="Asamblea Legislativa / Diario Oficial SV",
        source_urls=[
            "https://www.asamblea.gob.sv/",
            "https://www.diariooficial.gob.sv/",
            "https://imprentanacional.gob.sv/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="catalog-backed incomplete (Asamblea decretos + Diario Oficial API)",
        notes=(
            "Official Asamblea decree PDFs and Diario Oficial seleccion/ API issues. "
            "Thin OCR shells skipped. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
