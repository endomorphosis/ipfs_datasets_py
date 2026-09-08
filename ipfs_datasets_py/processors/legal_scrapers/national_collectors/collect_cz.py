#!/usr/bin/env python3
"""Czechia: official e-Sbírka NKOD JSON dumps (SPARQL fragment queries hang)."""
from __future__ import annotations
import gzip, json, logging, os, re, sys, time
from pathlib import Path
import ijson
import requests
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC, COUNTRY, SOURCE_TYPE = "cz", "Czechia", "e_sbirka"
LICENSE = (
    "e-Sbírka open data: not copyrighted / not protected (NKOD terms). "
    "https://opendata.eselpoint.gov.cz/datove-sady-esbirka/"
)
UA = DEFAULT_UA + " source=https://opendata.eselpoint.gov.cz/datove-sady-esbirka"
DUMP_BASE = "https://opendata.eselpoint.gov.cz/datove-sady-esbirka/"
FILES = {
    "acts": "002PravniAkt.json.gz",
    "wordings": "001PravniAktZneni.json.gz",
    "fragments": "004PravniAktFragment.json.gz",
}
log = logging.getLogger("cz")
FRAG_RE = re.compile(r"/frag_(\d+)\b")


def setup():
    ensure_dirs(CC)
    (ROOT / CC / "raw" / "dumps").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def download(fn: str) -> Path:
    dest = ROOT / CC / "raw" / "dumps" / fn
    url = DUMP_BASE + fn
    if dest.exists() and dest.stat().st_size > 10_000:
        log.info("dump exists %s bytes=%s", fn, dest.stat().st_size)
        return dest
    log.info("downloading %s", url)
    tmp = dest.with_suffix(dest.suffix + ".part")
    headers = {"User-Agent": UA}
    existing = tmp.stat().st_size if tmp.exists() else 0
    if existing:
        headers["Range"] = f"bytes={existing}-"
    with requests.get(url, stream=True, timeout=(30, 300), headers=headers) as r:
        if r.status_code == 416:
            tmp.replace(dest); return dest
        r.raise_for_status()
        mode = "ab" if r.status_code == 206 else "wb"
        if r.status_code != 206 and tmp.exists():
            tmp.unlink()
        n = existing if mode == "ab" else 0
        with tmp.open(mode) as fh:
            for chunk in r.iter_content(1024 * 256):
                if not chunk:
                    continue
                fh.write(chunk)
                n += len(chunk)
                if n and n % (50 * 1024 * 1024) < 256 * 1024:
                    log.info("  %s %s MB", fn, n // (1024 * 1024))
    tmp.replace(dest)
    log.info("saved %s bytes=%s", fn, dest.stat().st_size)
    return dest


def load_acts(path: Path) -> list[dict]:
    items = []
    with gzip.open(path, "rb") as fh:
        for obj in ijson.items(fh, "položky.item"):
            iri = obj.get("iri") or obj.get("akt-iri")
            if not iri:
                continue
            last = ((obj.get("právní-akt-znění-poslední") or {}) or {}).get("iri")
            if not last or "0000-00-00" in last:
                versions = obj.get("právní-akt-znění") or []
                dated = [v.get("iri") for v in versions if v.get("iri") and "0000-00-00" not in v.get("iri")]
                last = dated[-1] if dated else last
            items.append({
                "iri": iri,
                "citace": obj.get("akt-citace"),
                "title": obj.get("akt-název-vyhlášený") or obj.get("akt-citace"),
                "year": obj.get("akt-rok-předpisu"),
                "num": obj.get("akt-číslo-předpisu"),
                "kod": obj.get("akt-kód"),
                "last": last,
            })
            if len(items) % 10000 == 0:
                log.info("acts loaded %s", len(items))
    log.info("acts total %s", len(items))
    return items


def load_wording_frags(path: Path, wanted: set[str]) -> dict[str, list[int]]:
    """last-wording IRI -> ordered fragment ids from 001 dump."""
    out: dict[str, list[int]] = {}
    n = 0
    with gzip.open(path, "rb") as fh:
        for obj in ijson.items(fh, "položky.item"):
            iri = obj.get("iri")
            n += 1
            if n % 20000 == 0:
                log.info("wordings scanned %s kept=%s", n, len(out))
            if iri not in wanted:
                continue
            ids = []
            for frag in obj.get("právní-akt-znění-fragment") or []:
                firi = frag.get("iri") or ""
                m = FRAG_RE.search(firi)
                if m:
                    ids.append(int(m.group(1)))
            if ids:
                out[iri] = ids
    log.info("wordings with fragments %s / wanted %s", len(out), len(wanted))
    return out


def load_fragment_texts(path: Path, needed: set[int]) -> dict[int, str]:
    texts: dict[int, str] = {}
    n = 0
    with gzip.open(path, "rb") as fh:
        for obj in ijson.items(fh, "položky.item"):
            n += 1
            if n % 100000 == 0:
                log.info("fragments scanned %s kept=%s", n, len(texts))
            fid = obj.get("fragment-id")
            if fid not in needed:
                continue
            tx = obj.get("fragment-text")
            if tx:
                tx = re.sub(r"<[^>]+>", "", str(tx))
                texts[int(fid)] = tx.strip()
            if len(texts) == len(needed):
                break
    log.info("fragment texts %s / needed %s", len(texts), len(needed))
    return texts


def main():
    setup(); t0 = utcnow()
    try:
        p_acts = download(FILES["acts"])
        p_word = download(FILES["wordings"])
        p_frag = download(FILES["fragments"])
        acts = load_acts(p_acts)
        wanted = {a["last"] for a in acts if a.get("last")}
        mapping = load_wording_frags(p_word, wanted)
        needed: set[int] = set()
        for ids in mapping.values():
            needed.update(ids)
        log.info("needed fragment ids %s", len(needed))
        texts = load_fragment_texts(p_frag, needed)
    except Exception as exc:
        log.exception("dump load failed")
        write_summary(CC, country=COUNTRY, source="e-Sbírka NKOD JSON dumps",
                      source_urls=[DUMP_BASE, "https://opendata.eselpoint.gov.cz/sparql", "https://www.e-sbirka.cz/"],
                      license_text=LICENSE, discovered=0, fetched=0, skipped=0, failed=1,
                      coverage="catalog-backed incomplete",
                      notes=f"Official dump load failed: {exc}. SPARQL fragment queries time out (>20s even LIMIT 15).",
                      last_run=utcnow())
        return
    done = existing_ids(CC)
    ok = skip = fail = 0
    log.info("writing instruments acts=%s resume=%s", len(acts), len(done))
    for n, it in enumerate(acts, 1):
        year, num = it.get("year"), it.get("num")
        ident = f"{year}-{num}" if year and num else (it.get("kod") or it["iri"]).replace("esel-esb:", "")
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        ids = mapping.get(it.get("last") or "", [])
        parts = [texts[i] for i in ids if i in texts]
        text = "\n".join(parts)
        if len(text) < 40:
            log_failure(CC, {"identifier": ident, "source_url": it["iri"], "status": "failed", "reason": "empty_dump_text"})
            fail += 1
            continue
        title = it.get("title") or it.get("citace") or ident
        page = f"https://www.e-sbirka.cz/sb/{year}/{num}" if year else "https://www.e-sbirka.cz/"
        eli = "https://opendata.eselpoint.gov.cz/" + it["iri"].replace("esel-esb:", "esel-esb/")
        rec = base_record(
            cc=CC, country=COUNTRY, language="cs", ident=ident, title=title, text=text,
            source_url=page, source_type=SOURCE_TYPE, license_text=LICENSE, collector="cz-esbirka-nkod-dump",
            eli=eli, date=None, official_identifier=it.get("citace") or ident,
            document_type="statute", law_status="current", is_current=True,
            extra_meta={"discovery": {"method": "nkod_json_dump", "wording": it.get("last"),
                                      "fragments": len(ids)}},
        )
        write_instrument(CC, rec)
        done.add(rid)
        ok += 1
        if ok == 1 or ok % 200 == 0:
            log.info("progress n=%s ok=%s fail=%s skip=%s", n, ok, fail, skip)
            write_summary(CC, country=COUNTRY, source="e-Sbírka NKOD JSON dumps",
                          source_urls=[DUMP_BASE, "https://www.e-sbirka.cz/"],
                          license_text=LICENSE, discovered=len(acts), fetched=ok, skipped=skip, failed=fail,
                          coverage="catalog-backed incomplete",
                          notes="Official daily JSON dumps 002PravniAkt + 001PravniAktZneni + 004PravniAktFragment. SPARQL avoided (timeouts).",
                          last_run=utcnow())
    write_summary(CC, country=COUNTRY, source="e-Sbírka (Ministerstvo vnitra) NKOD JSON dumps",
                  source_urls=[DUMP_BASE, "https://opendata.eselpoint.gov.cz/sparql", "https://www.e-sbirka.cz/"],
                  license_text=LICENSE, discovered=len(acts), fetched=ok, skipped=skip, failed=fail,
                  coverage="full" if acts and fail == 0 else "catalog-backed incomplete",
                  notes="National Collection of Laws from official gzip dumps at opendata.eselpoint.gov.cz/datove-sady-esbirka (not copyrighted / not protected). SPARQL fragment graph timed out; dumps used instead. Current wording via právní-akt-znění-poslední.",
                  last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s fail=%s", len(acts), ok, fail)


if __name__ == "__main__":
    main()
