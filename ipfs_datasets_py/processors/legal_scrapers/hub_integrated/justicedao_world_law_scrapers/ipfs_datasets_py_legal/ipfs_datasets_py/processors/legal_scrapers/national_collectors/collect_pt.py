#!/usr/bin/env python3
"""Portugal: Diário da República ELI / dados.gov.pt. Site is an OutSystems SPA."""
from __future__ import annotations
import json, logging, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC, COUNTRY, SOURCE_TYPE = "pt", "Portugal", "dre"
LICENSE = "Diário da República (dre.pt / diariodarepublica.pt). Official gazette; check dre.pt legal notice for reuse."
UA = DEFAULT_UA + " source=https://diariodarepublica.pt/"
log = logging.getLogger("pt")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def main():
    setup(); t0 = utcnow()
    notes = []
    items = []
    seeds = [
        "https://diariodarepublica.pt/",
        "https://dre.pt/",
        "https://data.dre.pt/",
        "https://diariodarepublica.pt/dr/legislacao-consolidada",
        "https://dados.gov.pt/api/1/datasets/?q=Di%C3%A1rio+da+Rep%C3%BAblica&page_size=20",
        "https://dados.gov.pt/api/1/datasets/?q=dre+eli&page_size=20",
        "https://diariodarepublica.pt/dr/api",
        "http://data.dre.pt/eli/lei/1/2024/p/cons/20240101/pt/html",
        "https://dre.pt/dre/detalhe/lei/1-2024",
    ]
    for url in seeds:
        try:
            r = http_get(url, ua=UA, sleep=0.4, timeout=(15, 40), retries=2)
            notes.append(f"seed {url} -> HTTP {r.status_code} bytes={len(r.content or b'')} ct={r.headers.get('content-type','')[:40]}")
            rawp = ROOT / CC / "raw" / (re.sub(r"[^a-z0-9]+","_", url)[:90] + ".bin")
            rawp.write_bytes((r.content or b"")[:20000])
            if r.status_code == 200 and (r.headers.get("content-type") or "").startswith("application/json"):
                try:
                    data = r.json()
                    notes.append(f"  json keys={list(data)[:12] if isinstance(data, dict) else 'listn='+str(len(data))}")
                except Exception:
                    pass
            # collect ELI-looking hrefs
            if r.status_code == 200 and r.text:
                if "OutSystemsApp" in r.text or "app-root" in r.text or len(r.content) < 3000:
                    notes.append(f"  SPA/shell at {url}")
                for href in re.findall(r"https?://data\.dre\.pt/eli/[^\s\"'<>]+", r.text):
                    items.append({"url": href})
        except Exception as exc:
            notes.append(f"seed {url} ERROR {exc}")
    done = existing_ids(CC); ok = skip = fail = 0
    seen = set()
    uniq = []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"]); uniq.append(it)
    for it in uniq[:400]:
        ident = re.sub(r"^https?://", "", it["url"])
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1; continue
        r = http_get(it["url"], ua=UA, sleep=0.45, retries=2)
        if r.status_code != 200 or not r.content:
            fail += 1; continue
        text = html_to_text(r.text)
        if len(text) < 80 or "OutSystemsApp" in r.text:
            fail += 1; continue
        rec = base_record(cc=CC, country=COUNTRY, language="pt", ident=ident, title=ident, text=text,
                          source_url=it["url"], source_type=SOURCE_TYPE, license_text=LICENSE,
                          collector="pt-dre-eli", eli=it["url"], date=None, official_identifier=ident,
                          document_type="statute", law_status="unknown", is_current=None)
        write_instrument(CC, rec); ok += 1
    if not ok:
        notes.append(
            "Blocker: diariodarepublica.pt / dre.pt / data.dre.pt are an OutSystems SPA (~2KB shell). "
            "ELI templates exist (data.dre.pt/eli/{tipo}/{número}/{ano}/...) but year listings and consolidations "
            "are not server-rendered. dados.gov.pt has no bulk DRE act dump. Maximum legal slice this run: none."
        )
    write_summary(CC, country=COUNTRY, source="Diário da República (INCM)",
                  source_urls=["https://diariodarepublica.pt/", "https://dre.pt/", "https://data.dre.pt/",
                               "https://eur-lex.europa.eu/eli-register/portugal.html"],
                  license_text=LICENSE, discovered=len(uniq), fetched=ok, skipped=skip, failed=fail,
                  coverage="catalog-backed incomplete", notes="\n".join(notes), last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s fail=%s", len(uniq), ok, fail)


if __name__ == "__main__":
    main()
