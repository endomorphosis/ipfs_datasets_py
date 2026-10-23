#!/usr/bin/env python3
"""Dominican Republic: Consultoría Jurídica API + Congreso Biblioteca gacetas/leyes."""
from __future__ import annotations
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

CC, COUNTRY, LANG = "do", "Dominican Republic", "es"
SOURCE_TYPE = "consultoria_congreso_do"
LICENSE = (
    "Consultoría Jurídica del Poder Ejecutivo (consultoria.gov.do) / "
    "Biblioteca del Congreso Nacional (bibliotecadelcongreso.gob.do). "
    "Official Gaceta Oficial / legal texts. Authentic government text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.consultoria.gov.do/)"
ART = re.compile(r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s+[\d]+[º°o.]?)\b")
log = logging.getLogger("do")

CONSULTORIA = "https://www.consultoria.gov.do"
BIBLIO = "https://bibliotecadelcongreso.gob.do"
SKIP_CATS = {
    "nominas",
    "311-stats",
    "satisfaccion-informes",
    "servicios-carta",
}


def _ident_from_url(url: str, fallback: str) -> str:
    stem = Path(unquote(url.split("?")[0])).stem
    stem = re.sub(r"[^\w\-]+", "-", stem, flags=re.U).strip("-")[:140]
    return stem or fallback[:140]


def discover():
    items, seen = [], set()

    def add(url: str, *, ident: str | None = None, title: str | None = None, prefer: bool = False, date: str | None = None):
        url = (url or "").split("#")[0]
        if not url.startswith("http"):
            return
        low = url.lower()
        if ".pdf" not in low:
            return
        if not any(h in low for h in ("consultoria.gov.do", "bibliotecadelcongreso.gob.do")):
            return
        if any(low.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
            return
        key = url.lower()
        if key in seen:
            return
        seen.add(key)
        iid = ident or _ident_from_url(url, "doc")
        items.append((iid, url, title, prefer, date))

    # Consultoría Jurídica official /api/documents
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
                    if cat == "gacetas" and title.isdigit():
                        title = f"Gaceta Oficial No. {title}"
                    year = d.get("year")
                    month = d.get("month") or ""
                    if year and month and cat == "gacetas":
                        title = f"{title} ({month} {year})"
                    for p in pdfs:
                        full = urljoin(CONSULTORIA + "/", p)
                        add(
                            full,
                            ident=f"{cat}-{_ident_from_url(full, d.get('id') or 'doc')}",
                            title=title or None,
                            prefer=True,
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
                    prefer=True,
                )
    except Exception as exc:
        log.info("consultoria settings fail: %s", exc)

    # Biblioteca del Congreso Nacional
    for page, kind in (
        (f"{BIBLIO}/gaceta.htm", "gaceta"),
        (f"{BIBLIO}/leyes.htm", "leyes"),
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
            prefer = False
            m = re.search(r"(20\d{2})", href)
            if kind == "gaceta" and m and int(m.group(1)) >= 2000:
                prefer = True
            title = Path(unquote(href)).stem.replace("_", " ")
            if kind == "gaceta":
                title = f"Gaceta Oficial {title}"
            else:
                title = f"Leyes decretos resoluciones {title}"
            add(full, ident=_ident_from_url(full, kind), title=title, prefer=prefer)

    # CDX fallback legacy consultoria PDFs
    for prefix in ("www.consultoria.gov.do/", "consultoria.gov.do/"):
        for h in cdx_urls(
            prefix,
            limit=env_int("CDX_LIMIT", 200),
            match_type="prefix",
            extra_filters=["mimetype:application/pdf"],
        ):
            orig = (h.get("original") or "").replace("http://", "https://").replace(":80/", "/")
            if not orig or ".pdf" not in orig.lower():
                continue
            low = orig.lower()
            if any(x in low for x in ("nomina", "foto", "banner", "logo", ".jpg")):
                continue
            add(orig, prefer=False)

    def rank(item):
        ident, url, title, prefer, date = item
        low = url.lower()
        # Prefer individual consultoria uploads / constitutions over huge yearly tomos
        if "consultoria.gov.do/uploads/" in low:
            tier = 0
        elif "bibliotecadelcongreso.gob.do/gaceta/" in low:
            tier = 2  # yearly compilations — large but official
        elif "bibliotecadelcongreso.gob.do/leyes/" in low:
            tier = 3
        else:
            tier = 1 if prefer else 4
        # newer years first when present in URL
        import re as _re
        ys = _re.findall(r"(20\d{2})", url)
        year_key = -max(int(y) for y in ys) if ys else 0
        return (tier, year_key, url)

    items.sort(key=rank)
    out = [(i, u, t, d) for i, u, t, _, d in items]
    log.info("catalog %s", len(out))
    return out


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 3600)
    min_text = env_int("MIN_TEXT", 150)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for ident, url, title_hint, date in discover():
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
        source="Consultoría Jurídica / Biblioteca del Congreso DO",
        source_urls=[
            "https://www.consultoria.gov.do/",
            "https://www.consultoria.gov.do/api/documents",
            "https://bibliotecadelcongreso.gob.do/gaceta.htm",
            "https://bibliotecadelcongreso.gob.do/leyes.htm",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="catalog-backed incomplete (consultoria API gacetas + Congreso biblioteca)",
        notes=(
            "Official consultoria.gov.do Gaceta/uploads PDFs and Biblioteca del Congreso "
            "Gaceta Oficial / leyes PDFs. Nominas and non-law categories skipped. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
