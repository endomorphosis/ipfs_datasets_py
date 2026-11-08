#!/usr/bin/env python3
"""Guatemala: Congreso assets/uploads decretos/acuerdos PDFs. Prefer assets path; archivos/ is challenge-gated. Cap/Artículo densify regex (mid-line PDF columns)."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "gt", "Guatemala", "es"
SOURCE_TYPE = "congreso_gt"
LICENSE = (
    "Congreso de la República de Guatemala (congreso.gob.gt). "
    "Official legislative texts. Authentic official text prevails. Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://www.congreso.gob.gt/)"
)
ART = re.compile(
    r"(?m)(?:^|(?<=\n)|(?<=[ \t]{2}))"
    r"((?:ART[IÍ]CULO|ARTICULO|Art[íi]culo|Articulo|Artlculo|Artculo|ArtIculo|Art\.)\s*"
    r"(?:[\d]+|[IVXLC]{1,6}|[Uu]nico|[Pp]rimero|[Ss]egundo|[Tt]ercero|"
    r"[Cc]uarto|[Qq]uinto|[Ss]exto|[Ss][eé]ptimo|[Oo]ctavo|[Nn]oveno|[Dd][eé]cimo)"
    r"[A-Za-zº°o.\-]*(?:\s*(?:bis|ter|qu[aá]ter|quinquies|sexies|transitori[oa]))?"
    r"|"
    r"(?:CAP[IÍ]TULO|CAPITULO|Cap[ií]tulo|Capitulo|T[IÍ]TULO|TITULO|T[ií]tulo|Titulo|"
    r"SECCI[OÓ]N|SECCION|Secci[oó]n|Seccion|TiTULO)\s+"
    r"(?:[IVXLC]{1,8}|\d+[º°o.]?|[Pp]rimero|[Ss]egundo|[Uu]nico))"
    r"(?=\s*[.\-–:]|\s|$)"
)
log = logging.getLogger("gt")
SKIP_SUB = ("/actas_de_sesiones/", "/iniciativas/", "/dictamen/")


def discover():
    items, seen = [], set()
    def add(url):
        url = url.split("#")[0].replace("http://", "https://").replace(":80/", "/")
        if "congreso.gob.gt" not in url.lower():
            return
        if ".pdf" not in url.lower():
            return
        low = url.lower()
        if any(s in low for s in SKIP_SUB):
            return
        if "/assets/uploads/" not in low:
            return
        if url in seen:
            return
        ident = Path(url.split("?")[0]).stem[:160]
        seen.add(url)
        items.append((ident, url))
    for prefix in (
        "www.congreso.gob.gt/assets/uploads/info_legislativo/decretos/",
        "www.congreso.gob.gt/assets/uploads/info_legislativo/acuerdos/",
        "congreso.gob.gt/assets/uploads/info_legislativo/decretos/",
        "congreso.gob.gt/assets/uploads/info_legislativo/acuerdos/",
    ):
        for h in cdx_urls(
            prefix,
            limit=env_int("CDX_LIMIT", 2000),
            match_type="prefix",
            extra_filters=["mimetype:application/pdf"],
        ):
            orig = h.get("original") or ""
            if orig:
                add(orig)
    items.sort(key=lambda it: (0 if "/decretos/" in it[1].lower() else 1, it[1]))
    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 200)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for ident, url in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, verify=False, min_text=150)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 18:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_gt.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Congreso de la República de Guatemala",
        source_urls=["https://www.congreso.gob.gt/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (assets/uploads decretos+acuerdos; live browser-UA)",
        notes="Prefer assets/uploads; archivos/ challenge-gated. Not vLex. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
