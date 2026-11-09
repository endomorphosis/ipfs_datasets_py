#!/usr/bin/env python3
"""Dominican Republic densify: Consultoría Jurídica + Congreso Biblioteca (lean).

Official only:
  https://www.consultoria.gov.do/  (api/documents, api/settings, uploads)
  https://bibliotecadelcongreso.gob.do/  (leyes / gaceta)
Canonical Hub slug: ipfs_dominicanrepublic_laws (NOT ipfs_dominican_republic_laws).
Prefer leyes/códigos/constituciones/decretos/reglamentos; cap gazette shells.
No vLex / La Ley / Camara boletines / Senado admin PDFs.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, existing_ids, log_failure, utcnow, write_summary
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

CC, COUNTRY, LANG = "do", "Dominican Republic", "es"
SOURCE_TYPE = "consultoria_congreso_do"
LICENSE = (
    "Consultoría Jurídica del Poder Ejecutivo (consultoria.gov.do) / "
    "Biblioteca del Congreso Nacional (bibliotecadelcongreso.gob.do). "
    "Official Gaceta Oficial / legal texts. Authentic government text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.consultoria.gov.do/)"
# OCR-tolerant Artículo / Articulo / ARTICULO + letter suffixes / ordinales
ART = re.compile(
    r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo|lculo|tculo)?|ART[IÍ]CULO|ARTICULO)\s+"
    r"(?:[\d]+|[IVXLC]{1,6}|PRIMERO|SEGUNDO|TERCERO|CUARTO|QUINTO|SEXTO|S[EÉ]PTIMO|"
    r"OCTAVO|NOVENO|D[EÉ]CIMO)[A-Za-zº°o.\-]*)\b"
)
log = logging.getLogger("do")

CONSULTORIA = "https://www.consultoria.gov.do"
BIBLIO = "https://bibliotecadelcongreso.gob.do"
SKIP_CATS = {"nominas", "311-stats", "satisfaccion-informes", "servicios-carta"}
ALLOW_HOSTS = ("consultoria.gov.do", "bibliotecadelcongreso.gob.do")

def head_ok(url: str, timeout: float = 15.0) -> bool:
    """Fast live existence check; avoid lengthy Wayback on dead API fileUrls."""
    import requests
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    headers = {"User-Agent": UA, "Accept": "application/pdf,*/*"}
    try:
        r = requests.head(url, timeout=timeout, headers=headers, verify=False, allow_redirects=True)
        code = r.status_code or 0
        if code in (403, 405, 501):
            # some hosts reject HEAD — ranged GET
            r = requests.get(url, timeout=timeout, headers={**headers, "Range": "bytes=0-0"}, verify=False, allow_redirects=True)
            code = r.status_code or 0
        return code in (200, 206) or 200 <= code < 400
    except Exception:
        return False

LEYISH = re.compile(
    r"ley|c[oó]digo|constituc|decreto|reglamento|org[aá]nic|estatuto|c[oó]digo",
    re.I,
)


def _norm_url(url: str) -> str:
    u = (url or "").strip().split("#")[0].split("?")[0]
    u = u.replace("http://", "https://").replace(":80/", "/")
    return u.lower()


def _ident_from_url(url: str, fallback: str) -> str:
    stem = Path(unquote(url.split("?")[0])).stem
    stem = re.sub(r"[^\w\-]+", "-", stem, flags=re.U).strip("-")[:140]
    return stem or fallback[:140]


def seed_done_from_hub(done: set[str]) -> int:
    seed = Path(ROOT) / CC / "_hub_seed_ids.json"
    n0 = len(done)
    if seed.exists():
        try:
            for i in json.loads(seed.read_text(encoding="utf-8")):
                done.add(str(i))
                done.add(slug_id(CC, str(i)))
        except Exception as exc:
            log.info("hub seed fail %s", exc)
    urls_path = Path(ROOT) / CC / "_hub_urls.json"
    url_norms: set[str] = set()
    if urls_path.exists():
        try:
            url_norms = set(json.loads(urls_path.read_text(encoding="utf-8")))
        except Exception as exc:
            log.info("hub urls fail %s", exc)
    return len(done) - n0, url_norms


def discover(url_norms: set[str]):
    items, seen = [], set()

    def add(url: str, *, ident: str | None = None, title: str | None = None, tier: int = 5, date: str | None = None):
        url = (url or "").split("#")[0]
        if not url.startswith("http"):
            return
        low = url.lower()
        if ".pdf" not in low:
            return
        if not any(h in low for h in ALLOW_HOSTS):
            return
        if any(low.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
            return
        key = _norm_url(url)
        if key in seen:
            return
        seen.add(key)
        iid = ident or _ident_from_url(url, "doc")
        items.append((iid, url, title, tier, date, key))

    # Consultoría Jurídica /api/documents
    try:
        r = live_get(f"{CONSULTORIA}/api/documents", ua=UA, verify=False, retries=2, timeout=(20, 90))
        if getattr(r, "status_code", 0) == 200:
            docs = r.json()
            if isinstance(docs, list):
                log.info("consultoria documents=%s", len(docs))
                for d in docs:
                    cat = (d.get("category") or "").lower()
                    if cat in SKIP_CATS:
                        continue
                    fu = d.get("fileUrl") or ""
                    pdfs = [p.strip() for p in fu.split("|") if p.strip().lower().endswith(".pdf")]
                    if not pdfs:
                        continue
                    title = (d.get("title") or "").strip()
                    year = d.get("year")
                    month = d.get("month") or ""
                    if cat == "gacetas" and title.isdigit():
                        title = f"Gaceta Oficial No. {title}"
                        if year and month:
                            title = f"{title} ({month} {year})"
                    # lean tiers: marco/base/constit > named leyish uploads > recent gacetas > other
                    low_t = f"{title} {fu}".lower()
                    if cat in ("marco-legal-sistema", "base-legal"):
                        tier = 0
                    elif LEYISH.search(low_t) and "uploads/" in fu.lower():
                        tier = 1
                    elif cat == "gacetas":
                        try:
                            y = int(year) if year else 0
                        except Exception:
                            y = 0
                        # hashed upload filenames usually live; prefer recent
                        hashed = bool(re.search(r"/uploads/\d{10,}-", fu))
                        if hashed and y >= 2020:
                            tier = 1
                        elif y >= 2020:
                            tier = 3
                        else:
                            tier = 4
                    else:
                        tier = 2
                    for p in pdfs:
                        full = urljoin(CONSULTORIA + "/", p)
                        add(
                            full,
                            ident=f"{cat}-{_ident_from_url(full, str(d.get('id') or 'doc'))}",
                            title=title or None,
                            tier=tier,
                            date=str(year) if year else None,
                        )
    except Exception as exc:
        log.info("consultoria api documents fail: %s", exc)

    # Constitutions from /api/settings
    try:
        r = live_get(f"{CONSULTORIA}/api/settings", ua=UA, verify=False, retries=2, timeout=(20, 90))
        if getattr(r, "status_code", 0) == 200:
            settings = r.json() or {}
            constit = settings.get("coleccion_constituciones") or []
            log.info("constitutions=%s", len(constit))
            for c in constit:
                url = c.get("url") or ""
                if not url.lower().endswith(".pdf"):
                    continue
                full = urljoin(CONSULTORIA + "/", url)
                add(
                    full,
                    ident=f"const-{c.get('id') or _ident_from_url(full, 'const')}",
                    title=c.get("title") or c.get("detail") or "Constitución",
                    tier=0,
                )
    except Exception as exc:
        log.info("consultoria settings fail: %s", exc)

    # Biblioteca del Congreso — prefer leyes compilations lightly; cap old gaceta shells
    for page, kind in (
        (f"{BIBLIO}/leyes.htm", "leyes"),
        (f"{BIBLIO}/gaceta.htm", "gaceta"),
    ):
        try:
            r = live_get(page, ua=UA, verify=False, retries=2)
        except Exception as exc:
            log.info("biblio fail %s: %s", page, exc)
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        hrefs = re.findall(r'href="([^"]+\.pdf)"', r.text or "", re.I)
        log.info("biblio %s pdfs=%s", kind, len(hrefs))
        for href in hrefs:
            full = urljoin(page, href)
            ys = re.findall(r"(20\d{2}|19\d{2})", href)
            year = max(int(y) for y in ys) if ys else 0
            if kind == "leyes":
                # yearly tomos are huge; still official leyes — mid tier, prefer newer
                tier = 2 if year >= 1950 else 5
                title = f"Leyes decretos resoluciones {Path(unquote(href)).stem.replace('_', ' ')}"
            else:
                # gaceta yearly shells — only recent
                if year and year < 2000:
                    continue
                tier = 4
                title = f"Gaceta Oficial {Path(unquote(href)).stem.replace('_', ' ')}"
            add(full, ident=_ident_from_url(full, kind), title=title, tier=tier, date=str(year) or None)

    # Limited CDX for consultoria uploads missing from live API
    for prefix in ("www.consultoria.gov.do/uploads/",):
        for h in cdx_urls(
            prefix,
            limit=env_int("CDX_LIMIT", 80),
            match_type="prefix",
            extra_filters=["mimetype:application/pdf"],
        ):
            orig = (h.get("original") or "").replace("http://", "https://").replace(":80/", "/")
            if not orig or ".pdf" not in orig.lower():
                continue
            low = orig.lower()
            if any(x in low for x in ("nomina", "foto", "banner", "logo", ".jpg")):
                continue
            tier = 1 if LEYISH.search(low) else 5
            add(orig, tier=tier)

    def rank(item):
        ident, url, title, tier, date, key = item
        # skip already-on-hub URLs by pushing to end (still filtered later)
        hub_pen = 1 if key in url_norms else 0
        ys = re.findall(r"(20\d{2})", url)
        year_key = -max(int(y) for y in ys) if ys else 0
        return (hub_pen, tier, year_key, url)

    items.sort(key=rank)
    # Cap gazette shells in catalog (keep lean front)
    lean, gac, other = [], [], []
    for it in items:
        ident, url, title, tier, date, key = it
        if tier >= 3 and ("gaceta" in (ident or "").lower() or "gacetas-" in (ident or "").lower()):
            gac.append(it)
        elif tier <= 2:
            lean.append(it)
        else:
            other.append(it)
    max_gac = env_int("MAX_GACETA", 40)
    out_items = lean + other + gac[:max_gac]
    out = [(i, u, t, d, k) for i, u, t, _, d, k in out_items]
    log.info(
        "catalog %s (lean=%s other=%s gac_capped=%s/%s raw=%s)",
        len(out),
        len(lean),
        len(other),
        min(len(gac), max_gac),
        len(gac),
        len(items),
    )
    return out


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 100)
    max_seconds = env_int("MAX_SECONDS", 5400)
    min_text = env_int("MIN_TEXT", 150)
    t_start = time.time()
    done = existing_ids(CC)
    seeded, url_norms = seed_done_from_hub(done)
    log.info("seeded_ids=%s hub_urls=%s local_done=%s", seeded, len(url_norms), len(done))
    ok = skip = fail = skip_hub = 0
    for ident, url, title_hint, date, key in discover(url_norms):
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done or ident in done:
            skip += 1
            continue
        if key in url_norms:
            skip_hub += 1
            done.add(rid)
            continue
        # Skip dead consultoria named uploads quickly (API lists stale fileUrls)
        if "consultoria.gov.do/uploads/" in key and not head_ok(url):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "live_head_miss"})
            log.info("skip dead %s", ident[:70])
            continue
        got = fetch_official(url, ua=UA, verify=False, min_text=min_text, wayback=False)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        if len(re.sub(r"\s+", "", text)) < 100:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "thin_ocr_shell"})
            continue
        title = title_hint or first_title(text, ident)
        if title_hint and len(title_hint) > 12:
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
            collector="collect_do.py",
            date=date,
            article_re=ART,
            extra_meta={"fetch_method": got.get("method"), "densify": "americas_do_lean"},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC,
        country=COUNTRY,
        source="Consultoría Jurídica / Biblioteca del Congreso DO",
        source_urls=[
            "https://www.consultoria.gov.do/",
            "https://www.consultoria.gov.do/api/documents",
            "https://www.consultoria.gov.do/api/settings",
            "https://bibliotecadelcongreso.gob.do/gaceta.htm",
            "https://bibliotecadelcongreso.gob.do/leyes.htm",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail + skip_hub,
        fetched=ok,
        skipped=skip + skip_hub,
        failed=fail,
        coverage="catalog-backed incomplete (lean consultoria marco-legal/base-legal/constit + capped gacetas + Congreso biblioteca)",
        notes=(
            "Lean densify past Hub tip ipfs_dominicanrepublic_laws. Official consultoria.gov.do "
            "and bibliotecadelcongreso.gob.do only. Prefer leyes/códigos/decretos; cap gazette shells. "
            "Dual-slug note: use ipfs_dominicanrepublic_laws (not ipfs_dominican_republic_laws). Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s skip_hub=%s fail=%s", ok, skip, skip_hub, fail)


if __name__ == "__main__":
    main()
