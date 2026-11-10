#!/usr/bin/env python3
"""Append-only Italy deepen: catalog years 1908–2026 + fetch missing instruments.

- NEVER deletes/clobbers existing {_CORPORA}/it/instruments
- Appends to catalog.jsonl for new years only
- Does NOT Hub-publish
- Leaves other collectors alone
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, logging, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, "{_SCRAPERS.parent}/scrapers")
from common import (  # noqa: E402
    ROOT, DEFAULT_UA, ensure_dirs, existing_ids, get_session, html_to_text,
    http_get, iso_date, log_failure, slug_id, utcnow, write_instrument, write_summary,
    xml_to_text, base_record, append_catalog,
)

CC, COUNTRY, SOURCE_TYPE = "it", "Italy", "normattiva"
LICENSE = (
    "Normattiva OpenData (dati.normattiva.it). Official Italian legislation. "
    "Reuse per Normattiva OpenData terms. HTML from official dettaglio-atto API; "
    "Akoma Ntoso via caricaAKN when present."
)
UA = DEFAULT_UA + " source=https://dati.normattiva.it/ deepen=1908-2026"
API = "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1"
HDR = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": UA}
PT = timezone(timedelta(hours=-7))
LOGP = _CORPORA / "it" / "logs" / "deepen_1908_2026.out"
PIDP = _CORPORA / "it" / "logs" / "deepen_1908_2026.pid"
WAVE = _CORPORA / "_wave_logs" / "it_deepen_1908_2026.md"
YEAR_START, YEAR_END = 1908, 2026

log = logging.getLogger("it-deepen")


def now_pt() -> str:
    return datetime.now(PT).strftime("%Y-%m-%d %H:%M:%S PT")


def wave(extra: dict) -> None:
    lines = [
        "# Italy deepen 1908–2026 (append-only)",
        "",
        f"- updated_at: {now_pt()} / {utcnow()}",
        f"- goal: grow local instruments beyond Kingdom-era 47938 toward Republic coverage; arts via split_articles; NO Hub publish from this job",
        f"- restore_block: see it_restore_blocked.md (arts from local alone = 42 << 12246)",
        "",
        "## Progress",
        "",
    ]
    for k, v in extra.items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    WAVE.write_text("\n".join(lines), encoding="utf-8")


def api_post(path: str, payload: dict, retries: int = 4):
    last = None
    for attempt in range(1, retries + 1):
        try:
            time.sleep(0.35)
            r = get_session(UA).post(API + path, json=payload, timeout=(20, 90), headers=HDR)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(min(30, 2 ** attempt))
                last = r
                continue
            return r
        except Exception as exc:
            last = exc
            time.sleep(min(20, 1.5 * attempt))
    if isinstance(last, Exception):
        raise last
    return last


def load_existing_catalog_keys() -> set[tuple]:
    catp = ROOT / CC / "raw" / "catalog.jsonl"
    seen: set[tuple] = set()
    if not catp.exists():
        return seen
    for line in catp.open(encoding="utf-8"):
        try:
            row = json.loads(line)
        except Exception:
            continue
        key = (row.get("dataGU"), row.get("codiceRedazionale"))
        if key[1]:
            seen.add(key)
    return seen


def discover_years(seen: set[tuple]) -> list[dict]:
    items: list[dict] = []
    for year in range(YEAR_START, YEAR_END + 1):
        page = 1
        pages = 1
        while page <= pages and page <= 400:
            payload = {
                "dataInizioEmanazione": f"{year}-01-01",
                "dataFineEmanazione": f"{year}-12-31",
                "orderType": "vecchio",
                "paginazione": {"paginaCorrente": page, "numeroElementiPerPagina": 50},
            }
            try:
                r = api_post("/api/v1/ricerca/avanzata", payload)
            except Exception as exc:
                log.info("search %s p%s err %s", year, page, exc)
                break
            if r.status_code != 200:
                log.info("search %s p%s HTTP %s %s", year, page, r.status_code, r.text[:160])
                break
            try:
                data = r.json()
            except Exception:
                break
            rows = data.get("listaAtti") or []
            found = int(data.get("numeroAttiTrovati") or 0)
            pages = int(data.get("numeroPagine") or 1) or 1
            new_this = 0
            for row in rows:
                key = (row.get("dataGU"), row.get("codiceRedazionale"))
                if not key[1] or key in seen:
                    continue
                seen.add(key)
                rec = {
                    "dataGU": row.get("dataGU"),
                    "codiceRedazionale": row.get("codiceRedazionale"),
                    "titoloAtto": row.get("titoloAtto"),
                    "denominazioneAtto": row.get("denominazioneAtto"),
                    "numeroAtto": row.get("numeroAtto"),
                    "annoProvvedimento": row.get("annoProvvedimento"),
                    "dataEmanazione": row.get("dataEmanazione"),
                    "numeroGU": row.get("numeroGU"),
                    "deepen_year": year,
                }
                items.append(rec)
                append_catalog(CC, rec)
                new_this += 1
            log.info(
                "year %s p%s/%s rows=%s new=%s catalog_new_total=%s found=%s",
                year, page, pages, len(rows), new_this, len(items), found,
            )
            if page == 1 or page % 5 == 0:
                wave({
                    "phase": "discover",
                    "year": year,
                    "page": f"{page}/{pages}",
                    "new_catalog_rows": len(items),
                    "pid": Path(PIDP).read_text().strip() if PIDP.exists() else "?",
                })
            if not rows:
                break
            page += 1
    return items


def fetch_text(row: dict) -> tuple[str, str, str]:
    data_gu = str(row.get("dataGU") or "")
    codice = str(row.get("codiceRedazionale") or "")
    title = (row.get("titoloAtto") or "").strip("[] ").strip()
    src = f"https://www.normattiva.it/atto/caricaDettaglioAtto?dataGU={data_gu}&codiceRedazionale={codice}"
    r = api_post("/api/v1/atto/dettaglio-atto", {
        "dataGU": data_gu, "codiceRedazionale": codice, "formatoRichiesta": "V",
    })
    if r.status_code == 200 and r.content:
        try:
            data = r.json()
        except Exception:
            data = {}
        atto = ((data.get("data") or {}).get("atto")) or data.get("atto") or {}
        html = atto.get("articoloHtml") or atto.get("html") or ""
        if atto.get("titolo"):
            title = atto.get("titolo")
        if html:
            return html_to_text(html), src, title
    dgu = data_gu.replace("-", "")
    akn = f"https://www.normattiva.it/do/atto/caricaAKN?dataGU={dgu}&codiceRedaz={codice}&dataVigenza=20260902"
    rr = http_get(akn, ua=UA, sleep=0.4)
    if rr.status_code == 200 and rr.content and (b"<akoma" in rr.content[:500].lower() or b"<?xml" in rr.content[:40]):
        return xml_to_text(rr.text), akn, title
    return "", src, title


def fetch_one(row: dict, done: set[str]) -> str:
    data_gu = str(row.get("dataGU") or "")
    codice = str(row.get("codiceRedazionale") or "")
    ident = f"{data_gu}-{codice}" if codice else json.dumps(row)[:40]
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    text, src, title = fetch_text(row)
    if not text or len(text) < 40:
        log_failure(CC, {"identifier": ident, "source_url": src, "status": "failed", "reason": "empty_text", "deepen": "1908-2026"})
        return "fail"
    dtype = (row.get("denominazioneAtto") or "statute").lower()
    rec = base_record(
        cc=CC, country=COUNTRY, language="it", ident=ident, title=title or ident, text=text,
        source_url=src, source_type=SOURCE_TYPE, license_text=LICENSE, collector="it-normattiva-opendata-deepen-1908-2026",
        eli=None, date=iso_date(data_gu or row.get("dataEmanazione")),
        official_identifier=ident, document_type=dtype, law_status="current", is_current=True,
        extra_meta={"discovery": {"method": "ricerca_avanzata_deepen", "codiceRedazionale": codice,
                                  "denominazioneAtto": row.get("denominazioneAtto"), "year_span": "1908-2026"}},
    )
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def main() -> None:
    ensure_dirs(CC)
    import os
    PIDP.write_text(str(os.getpid()))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOGP, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    t0 = utcnow()
    log.info("START deepen 1908-2026 pid=%s", os.getpid())
    wave({"phase": "start", "pid": os.getpid(), "instruments_before": len(existing_ids(CC))})
    seen = load_existing_catalog_keys()
    log.info("existing catalog keys %s", len(seen))
    items = discover_years(seen)
    log.info("discover done new_items=%s", len(items))
    done = existing_ids(CC)
    ok = skip = fail = 0
    if not items:
        wave({"phase": "discover_empty", "new_catalog_rows": 0, "pid": os.getpid()})
        log.info("no new catalog rows for 1908-2026")
        return
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(fetch_one, it, done) for it in items]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc), "deepen": "1908-2026"})
            ok += st == "ok"
            skip += st == "skip"
            fail += st == "fail"
            if n % 50 == 0 or n == len(items):
                inst_n = len(list((ROOT / CC / "instruments").glob("*.json")))
                log.info("fetch progress %s/%s ok=%s fail=%s skip=%s instruments_now=%s", n, len(items), ok, fail, skip, inst_n)
                wave({
                    "phase": "fetch",
                    "progress": f"{n}/{len(items)}",
                    "ok": ok, "fail": fail, "skip": skip,
                    "instruments_now": inst_n,
                    "pid": os.getpid(),
                    "started": t0,
                })
    inst_n = len(list((ROOT / CC / "instruments").glob("*.json")))
    write_summary(
        CC, country=COUNTRY, source="Normattiva OpenData deepen 1908-2026",
        source_urls=["https://www.normattiva.it/", "https://dati.normattiva.it/", API],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete",
        notes="Append-only deepen for years 1908-2026. Existing Kingdom-era instruments preserved. No Hub publish.",
        last_run=utcnow(), extra=f"started {t0} instruments_now={inst_n}",
    )
    wave({
        "phase": "done",
        "ok": ok, "fail": fail, "skip": skip,
        "new_catalog_rows": len(items),
        "instruments_now": inst_n,
        "pid": os.getpid(),
        "started": t0,
        "finished": utcnow(),
    })
    log.info("DONE ok=%s fail=%s skip=%s instruments=%s", ok, fail, skip, inst_n)


if __name__ == "__main__":
    main()
