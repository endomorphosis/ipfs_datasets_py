#!/usr/bin/env python3
"""Algeria: Journal Officiel (JORADP / SGG) official PDF issues over HTTP."""
from __future__ import annotations
import logging, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "dz", "Algeria", "fr"
SOURCE_TYPE = "joradp"
LICENSE = (
    "Journal Officiel de la République Algérienne Démocratique et Populaire "
    "(joradp.dz, Secrétariat Général du Gouvernement). JO authentic text prevails. "
    "Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=http://www.joradp.dz/)"
ART = None
log = logging.getLogger("dz")
# Codes hosted as standalone PDFs on JORADP
CODES = [
    ("constitution-fr", "http://www.joradp.dz/TRV/FCons.pdf", "Constitution (FR)"),
    ("constitution-ar", "http://www.joradp.dz/TRV/ACons.pdf", "الدستور"),
    ("code-penal-fr", "http://www.joradp.dz/TRV/FPenal.pdf", "Code pénal"),
    ("code-civil-fr", "http://www.joradp.dz/TRV/FCivil.pdf", "Code civil"),
    ("code-proc-penale-fr", "http://www.joradp.dz/TRV/FPPenal.pdf", "Code de procédure pénale"),
    ("code-proc-civile-fr", "http://www.joradp.dz/TRV/FPCivile.pdf", "Code de procédure civile"),
    ("code-famille-fr", "http://www.joradp.dz/TRV/FFam.pdf", "Code de la famille"),
    ("code-commerce-fr", "http://www.joradp.dz/TRV/FCom.pdf", "Code de commerce"),
    ("code-nationalite-fr", "http://www.joradp.dz/TRV/FNat.pdf", "Code de la nationalité"),
]


def jo_urls():
    years = list(range(env_int("YEAR_FROM", 2020), env_int("YEAR_TO", 2027)))
    years.reverse()
    maxn = env_int("JO_MAX_NUM", 90)
    out = []
    for y in years:
        for n in range(1, maxn + 1):
            ident = f"F{y}{n:03d}"
            url = f"http://www.joradp.dz/FTP/jo-francais/{y}/F{y}{n:03d}.pdf"
            out.append((ident, url, f"Journal Officiel n° {n} ({y}) — édition française"))
    return out


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 70)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    done = existing_ids(CC)
    items = list(CODES) + jo_urls()
    ok = skip = fail = 0
    for ident, url, title in items:
        if max_new and ok >= max_new:
            break
        if max_seconds and (time.time() - t_start) > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, verify=False, min_text=80)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        year = None
        if ident.startswith("F") and ident[1:5].isdigit():
            year = f"{ident[1:5]}-01-01"
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident, title=title, text=text,
            source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
            collector="collect_dz.py", date=year,
            extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s bytes=%s", ident, len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="JORADP Journal Officiel PDFs",
        source_urls=["http://www.joradp.dz/", "https://www.joradp.dz/FTP/jo-francais/"],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="codes + recent JO issues incomplete",
        notes="HTTP PDF (live TLS often EOF). Official JO issues/codes. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
