#!/usr/bin/env python3
"""Ecuador: official gob.ec regulaciones API + Registro Oficial PDFs."""
from __future__ import annotations
import html as htmlmod
import logging, re, sys, time
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, existing_ids, get_session, log_failure, utcnow, write_summary
from world_lib import env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "ec", "Ecuador", "es"
SOURCE_TYPE = "gob_ec_registro_oficial"
LICENSE = (
    "Official regulations published via gob.ec (Guía Oficial de Trámites y Servicios) "
    "with Registro Oficial metadata. Registro Oficial authentic text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.gob.ec/api)"
API = "https://www.gob.ec/api/v1/regulaciones"
ART = re.compile(r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s+[\d]+[A-Za-zº°.]?)\b")
LEY_TIPO = re.compile(r"ley|constituci|c[oó]digo", re.I)
log = logging.getLogger("ec")


def discover() -> list[dict]:
    sess = get_session(UA)
    items, seen = [], set()
    max_pages = env_int("MAX_PAGES", 16)
    for page in range(0, max_pages):
        try:
            time.sleep(0.25)
            r = sess.get(API, params={"page": page}, timeout=(20, 60), headers={"User-Agent": UA, "Accept": "application/json"})
        except Exception as exc:
            log.info("api page %s %s", page, exc)
            break
        if r.status_code != 200:
            log.info("api HTTP %s page %s", r.status_code, page)
            break
        try:
            rows = r.json() or []
        except Exception:
            break
        if not rows:
            break
        for row in rows:
            rid = str(row.get("regulacion_id") or "")
            if not rid or rid in seen:
                continue
            tipo = str(row.get("tipo") or "")
            title = htmlmod.unescape(str(row.get("regulacion") or ""))
            if env_int("LAWS_ONLY", 1) and not LEY_TIPO.search(tipo + " " + title):
                continue
            seen.add(rid)
            items.append(row)
        log.info("page %s kept=%s batch=%s", page, len(items), len(rows))
    return items


def archivo_url(row: dict) -> str:
    u = (row.get("archivo") or "").strip()
    if not u:
        return row.get("url") or ""
    u = u.replace("https://www.gob.ec//", "https://www.gob.ec/")
    if u.startswith("//"):
        u = "https:" + u
    if u.startswith("/"):
        u = urljoin("https://www.gob.ec/", u)
    return u


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 90)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    done = existing_ids(CC)
    items = discover()
    ok = skip = fail = 0
    for row in items:
        if max_new and ok >= max_new:
            break
        if max_seconds and (time.time() - t_start) > max_seconds:
            break
        ident = str(row.get("regulacion_id"))
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        url = archivo_url(row) or row.get("url") or ""
        if not url:
            fail += 1
            continue
        got = fetch_official(url, ua=UA, min_text=100)
        text = got.get("text") or ""
        if got.get("status") != "success":
            # fall back to gob.ec regulation HTML page
            page = row.get("url") or ""
            if page and page != url:
                got = fetch_official(page, ua=UA, min_text=100)
                text = got.get("text") or ""
        if got.get("status") != "success" or len(text) < 100:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        title = htmlmod.unescape(str(row.get("regulacion") or f"Regulación {ident}"))[:240]
        date = row.get("registro_oficial_fecha")
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident, title=title, text=text,
            source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
            collector="collect_ec.py", date=date, article_re=ART,
            extra_meta={"tipo": row.get("tipo"), "ro_numero": row.get("registro_oficial_numero"),
                        "fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s %s", ident, title[:60])
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="gob.ec regulaciones + Registro Oficial files",
        source_urls=["https://www.gob.ec/api/v1/regulaciones", "https://www.registroficial.gob.ec/"],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (leyes/códigos/constitución filter)",
        notes="Official gob.ec JSON catalog and attached PDFs. Registro Oficial prevails. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
