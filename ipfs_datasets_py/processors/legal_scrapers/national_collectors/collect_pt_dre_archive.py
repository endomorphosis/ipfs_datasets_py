#!/usr/bin/env python3
"""Portugal deepening: Diário da República via Wayback captures of dre.pt.

The live DRE (diariodarepublica.pt / dre.pt / data.dre.pt) is an OutSystems SPA:
detail pages and the ELI /pt/html endpoints render client-side and are not
scriptable without a browser. The pre-SPA Liferay DRE
(dre.pt/home/-/dre/<docid>/details/maximized) was server-rendered and is
extensively captured by the Wayback Machine, with title, Tipo de Diploma,
Publicação (DR number/series/date), Emissor, Sumário and full Texto.

Discovery: enumerate archived doc ids via Wayback CDX of dre.pt/home/-/dre*
(cached at raw/pt_dre_docids.txt). Fetch the latest capture
(/web/2id_/<original-url>) and parse.

Idempotent: skips instrument ids already present.
"""
from __future__ import annotations
import concurrent.futures
import logging
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *  # noqa

CC, COUNTRY, SOURCE_TYPE = "pt", "Portugal", "dre"
LICENSE = ("Diário da República (dre.pt). Official gazette of the Portuguese Republic "
           "(INCM). Retrieved via Wayback Machine captures of the official dre.pt pages. "
           "Not legal advice.")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
log = logging.getLogger("pt-dre")

MAX_NEW = int(os.environ.get("MAX_NEW", "800"))
MAX_SECONDS = int(os.environ.get("MAX_SECONDS", "3600"))
FETCH_BUDGET = int(os.environ.get("PT_FETCH_BUDGET", "2400"))
WORKERS = int(os.environ.get("PT_WORKERS", "3"))

CDX = ("https://web.archive.org/cdx/search/cdx?url=dre.pt/home/-/dre&matchType=prefix"
       "&fl=original&collapse=urlkey&limit=10000&page={page}")

LAW_TYPES = {"lei", "lei orgânica", "decreto-lei", "decreto legislativo regional",
             "decreto", "decreto regulamentar", "decreto regulamentar regional",
             "resolução do conselho de ministros", "resolução da assembleia da república",
             "portaria"}


def discover_ids(session) -> list[int]:
    cache = ROOT / CC / "raw" / "pt_dre_docids.txt"
    if cache.exists():
        ids = [int(x) for x in cache.read_text().split() if x.isdigit()]
        if ids:
            return ids
    ids: set[int] = set()
    for page in range(12):
        try:
            r = session.get(CDX.format(page=page), timeout=90)
            if r.status_code != 200 or not r.text.strip():
                break
            n0 = len(ids)
            for m in re.finditer(r"/home/-/dre/(\d+)/details", r.text):
                ids.add(int(m.group(1)))
            if len(ids) == n0:
                break
            time.sleep(1.0)
        except Exception as exc:
            log.warning("cdx page %s failed: %s", page, exc)
            break
    ordered = sorted(ids)
    if ordered:
        cache.write_text("\n".join(str(x) for x in ordered) + "\n", encoding="utf-8")
    return ordered


def clean_text(html: str) -> str:
    t = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    t = re.sub(r"(?is)<style.*?>.*?</style>", " ", t)
    t = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    import html as ih
    t = ih.unescape(t).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def parse_page(html: str, docid: int) -> dict | None:
    text = clean_text(html)
    if len(text) < 500:
        return None
    if "JavaScript is required" in text[:2000]:
        return None
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    title = re.sub(r"\s*-\s*DRE\s*$", "", title)
    if not title or len(title) < 4:
        return None
    if re.match(r"Diário da República n\.º", title):
        return None  # gazette issue index page, not a single act
    tipo = None
    m = re.search(r"Tipo de Diploma:\s*([A-Za-zÀ-ÿ0-9.ºª\-/() ]+?)(?=\s+(Parte|Número|Páginas|Sumário|Texto)\s*:)",
                  text)
    if m:
        tipo = re.sub(r"\s+", " ", m.group(1)).strip(" -–—:")
    if not tipo:
        # fall back to the act title's leading type word
        m = re.match(r"(Lei Orgânica|Decreto-Lei|Decreto Legislativo Regional|"
                     r"Decreto Regulamentar Regional|Decreto Regulamentar|Decreto|"
                     r"Lei|Portaria|Resolução|Despacho|Aviso|Declaração|Acórdão|"
                     r"Anúncio|Contrato|Deliberação|Edital|Louvor|Parecer|Recomendação)",
                     title, re.I)
        if m:
            tipo = m.group(1)
    serie = None
    m = re.search(r"Série\s+(I{1,3}|II)(-[A-Z])?", text)
    if m:
        serie = m.group(0).strip()
    date = None
    m = re.search(r"Publicação:[^\n]*?de\s+(\d{4}-\d{2}-\d{2})", text)
    if m:
        date = m.group(1)
    emissor = None
    m = re.search(r"Emissor:\s*([^\n]{2,160}?)(?=\s*Tipo de Diploma:|\s*Sumário|\s*Número:|\n)", text)
    if m:
        emissor = m.group(1).strip()
    numero = None
    m = re.search(r"Número:\s*([^\s\n]{1,30})", text)
    if m:
        numero = m.group(1).strip()
    # body: from "Texto" heading onward; fall back to full text
    body = text
    i = text.find("\nTexto\n")
    if i < 0:
        i = text.find(" Texto ")
    if i >= 0:
        body = text[i:].strip()
    if len(body) < 300:
        body = text
    return {"title": title, "tipo": tipo, "serie": serie, "date": date,
            "emissor": emissor, "numero": numero, "text": body, "docid": docid}


def is_priority(parsed: dict) -> bool:
    tipo = (parsed.get("tipo") or "").lower()
    serie = (parsed.get("serie") or "").upper()
    return tipo in LAW_TYPES and re.match(r"SÉRIE I(-|$)", serie) is not None


def doc_type_pt(tipo: str | None) -> str:
    t = (tipo or "").lower()
    if t in ("lei", "lei orgânica", "decreto-lei", "decreto legislativo regional"):
        return "statute"
    if "decreto" in t:
        return "decree"
    if "resolução" in t or "resolucao" in t:
        return "resolution"
    if "portaria" in t:
        return "regulation"
    if "acórdão" in t or "acordao" in t:
        return "decision"
    return "legal_act"


def fetch_doc(session, docid: int):
    orig = f"https://dre.pt/home/-/dre/{docid}/details/maximized"
    url = f"https://web.archive.org/web/2id_/{orig}"
    for attempt in range(2):
        try:
            r = session.get(url, timeout=60)
            if r.status_code == 404:
                return docid, None, "404"
            if r.status_code != 200:
                return docid, None, f"http_{r.status_code}"
            html = r.content.decode("utf-8", errors="replace")
            parsed = parse_page(html, docid)
            if not parsed:
                return docid, None, "unparseable"
            parsed["orig_url"] = orig
            parsed["capture_url"] = r.url
            return docid, parsed, None
        except Exception as exc:
            err = str(exc)[:80]
            time.sleep(3 + attempt * 3)
    return docid, None, err


def main():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "pt_dre.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    t0 = time.time()
    notes = []
    session = get_session(ua=UA, pool=WORKERS + 2)

    ids = discover_ids(session)
    notes.append(f"discovery: {len(ids)} dre.pt doc ids (Wayback CDX)")
    stride = 7
    ordered = [i for off in range(stride) for i in sorted(ids)[off::stride]]
    done = existing_ids(CC)
    notes.append(f"already existing instruments: {len(done)}")

    fetched = failed = skipped = 0
    written = 0
    deferred: list[dict] = []
    deadline = t0 + MAX_SECONDS
    _warned = {"v": False}

    def keep(parsed: dict):
        nonlocal written
        ident = f"dre-{parsed['docid']}"
        rid = slug_id(CC, ident)
        if rid in done:
            return "skip"
        official = parsed["numero"] or parsed["title"]
        rec = base_record(
            cc=CC, country=COUNTRY, language="pt", ident=ident, title=parsed["title"],
            text=parsed["text"], source_url=parsed["orig_url"], source_type=SOURCE_TYPE,
            license_text=LICENSE, collector="pt-dre-archive",
            date=parsed["date"], official_identifier=f"PT {official}",
            document_type=doc_type_pt(parsed["tipo"]), law_status="current", is_current=True,
            extra_meta={"dre_docid": parsed["docid"], "tipo_diploma": parsed["tipo"],
                        "serie": parsed["serie"], "emissor": parsed["emissor"],
                        "capture_url": parsed["capture_url"]},
        )
        try:
            err = validate_record(rec)
        except Exception as exc:
            err = str(exc)
        if err and ("_templates" in err or "jsonschema" in err or "No module named" in err):
            if not _warned["v"]:
                log.warning("schema validation unavailable; writing without it")
                notes.append("validation skipped: schema file not shipped in this environment")
                _warned["v"] = True
            err = None
        if err:
            log_failure(CC, {"docid": parsed["docid"], "error": f"validate: {err[:120]}"})
            return "fail"
        write_instrument(CC, rec)
        done.add(rid)
        return "ok"

    idx = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        pending = {}

        def feed():
            nonlocal idx
            while idx < len(ordered) and len(pending) < WORKERS * 3 \
                    and fetched + failed < FETCH_BUDGET and written < MAX_NEW \
                    and time.time() < deadline:
                docid = ordered[idx]; idx += 1
                if slug_id(CC, f"dre-{docid}") in done:
                    skipped += 1
                    continue
                pending[ex.submit(fetch_doc, session, docid)] = docid

        feed()
        while pending and written < MAX_NEW and time.time() < deadline:
            for fut in concurrent.futures.as_completed(list(pending)):
                docid = pending.pop(fut)
                try:
                    _d, parsed, err = fut.result()
                except Exception as exc:
                    parsed, err = None, str(exc)[:80]
                if parsed is None:
                    failed += 1
                    if failed <= 25:
                        log_failure(CC, {"docid": docid, "error": err})
                else:
                    fetched += 1
                    if is_priority(parsed):
                        res = keep(parsed)
                        if res == "ok":
                            written += 1
                        elif res == "fail":
                            failed += 1
                        else:
                            skipped += 1
                    else:
                        deferred.append(parsed)
                feed()
                if fetched % 100 == 0:
                    log.info("progress fetched=%d written=%d failed=%d skipped=%d",
                             fetched, written, failed, skipped)
            feed()

    for parsed in deferred:
        if written >= MAX_NEW or time.time() >= deadline:
            break
        res = keep(parsed)
        if res == "ok":
            written += 1
        elif res == "fail":
            failed += 1
        else:
            skipped += 1

    notes.append(f"fetch results: parsed_ok={fetched} failed={failed} skipped_existing={skipped}")
    notes.append("priority: Série I Lei/Decreto-Lei/etc first, then other DR acts to fill slots")
    notes.append("Blockers: live dre.pt/diariodarepublica.pt/data.dre.pt are an OutSystems SPA; "
                 "ELI /pt/html endpoints redirect to SPA error page. Used official pages via Wayback.")
    write_summary(
        CC, country=COUNTRY,
        source="Diário da República (dre.pt, official pages via Wayback Machine captures)",
        source_urls=["https://dre.pt/", "https://diariodarepublica.pt/", "https://data.dre.pt/"],
        license_text=LICENSE, discovered=len(ids), fetched=written,
        skipped=skipped, failed=failed, coverage="official-hosted-snapshot",
        notes="\n".join(notes), last_run=utcnow(),
        extra=f"started {utcnow()} (run t0 epoch {int(t0)}); collector=pt-dre-archive",
    )
    log.info("done discovered=%d written=%d failed=%d skipped=%d", len(ids), written, failed, skipped)


if __name__ == "__main__":
    main()
