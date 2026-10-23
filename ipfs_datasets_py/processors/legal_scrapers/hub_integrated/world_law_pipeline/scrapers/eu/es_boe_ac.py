#!/usr/bin/env python3
"""Spain BOE autonomous-community (autonómica) consolidada law — EU lane.

Open-data API only (robots.txt allows /datosabiertos/; disallows search result URLs and
some xml/pdf mirrors). Scope: ámbito Autonómico (codigo=2) → place_id iso:ES-XX (adm1).
Does NOT scrape provincial BOP gazettes (asia_latam es_bop.py).

Endpoints (verified 2026-10-11):
  GET https://www.boe.es/datosabiertos/api/legislacion-consolidada
      ?query={"query":{"query_string":{"query":"ambito@codigo:2"}}}&limit=500&offset=N
      Accept: application/json
  GET .../legislacion-consolidada/id/{id}/texto   Accept: application/xml

Docs: https://www.boe.es/datosabiertos/documentos/APIconsolidada.pdf
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import argparse
import gc
import html as _html
import json
import logging
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests

sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.rfc9309 import RobotsCache  # noqa: E402
from common.xwalk import XWALK  # noqa: E402  # ES es_ine available; AC uses iso:ES-XX

try:
    from schema import place_key as schema_place_key, validate_file, validate_record
except Exception as e:  # noqa: BLE001
    validate_file = validate_record = None  # type: ignore
    def schema_place_key(pid: str) -> str:  # type: ignore
        return pid.replace(":", "_")
    logging.getLogger("es_boe_ac").warning("schema import failed (%s)", e)

UA = ("world-municipal-law-research/1.0 (EU lane; endomorphosis/ipfs_datasets_py; "
      "+https://huggingface.co/datasets/endomorphosis/world_municipal_law)")
API = "https://www.boe.es/datosabiertos/api/legislacion-consolidada"
QUERY_AC = json.dumps({"query": {"query_string": {"query": "ambito@codigo:2"}}}, separators=(",", ":"))
MIN_DELAY = 0.75
BATCH_DOCS = 80
BATCH_BYTES = 12 * 1024 * 1024

OUT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu"))
ES_DIR = OUT / "ES"
UNM_DIR = OUT / "_unmatched"
STATE = OUT / "_state" / "es_boe_ac"
LOG_DIR = OUT / "_logs"
RAW_DIR = OUT / "_raw" / "es_boe_ac"
INV_DIR = OUT / "_invalid"

# ISO 3166-2 autonomous communities / cities (SCHEMA §3 adm1). Not invented: official codes.
CCAA_ISO = {
    "AN", "AR", "AS", "IB", "CN", "CB", "CL", "CM", "CT", "EX",
    "GA", "MD", "MC", "NC", "PV", "RI", "VC", "CE", "ML",
}
CCAA_BY_NAME = [
    ("andaluc", "AN"), ("arag", "AR"), ("asturias", "AS"), ("balears", "IB"), ("baleares", "IB"),
    ("canarias", "CN"), ("cantabria", "CB"), ("castilla y le", "CL"), ("castilla-la mancha", "CM"),
    ("castilla la mancha", "CM"), ("catalu", "CT"), ("extremadura", "EX"), ("galicia", "GA"),
    ("madrid", "MD"), ("murcia", "MC"), ("navarra", "NC"), ("vasco", "PV"), ("euskadi", "PV"),
    ("rioja", "RI"), ("valencia", "VC"), ("valenciana", "VC"), ("ceuta", "CE"), ("melilla", "ML"),
]
CCAA_NAMES = {
    "AN": "Comunidad Autónoma de Andalucía", "AR": "Comunidad Autónoma de Aragón",
    "AS": "Comunidad Autónoma del Principado de Asturias",
    "IB": "Comunidad Autónoma de las Illes Balears", "CN": "Comunidad Autónoma de Canarias",
    "CB": "Comunidad Autónoma de Cantabria", "CL": "Comunidad de Castilla y León",
    "CM": "Comunidad Autónoma de Castilla-La Mancha", "CT": "Comunidad Autónoma de Cataluña",
    "EX": "Comunidad Autónoma de Extremadura", "GA": "Comunidad Autónoma de Galicia",
    "MD": "Comunidad de Madrid", "MC": "Comunidad Autónoma de la Región de Murcia",
    "NC": "Comunidad Foral de Navarra", "PV": "Comunidad Autónoma del País Vasco",
    "RI": "Comunidad Autónoma de La Rioja", "VC": "Comunitat Valenciana",
    "CE": "Ciudad de Ceuta", "ML": "Ciudad de Melilla",
}

log = logging.getLogger("es_boe_ac")
_sess: Optional[requests.Session] = None
_robots: Optional[RobotsCache] = None
_last = 0.0


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "es_boe_ac.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def session() -> requests.Session:
    global _sess
    if _sess is None:
        _sess = requests.Session()
        _sess.headers.update({"User-Agent": UA})
    return _sess


def robots() -> RobotsCache:
    global _robots
    if _robots is None:
        def sf(_base: str):
            return session()
        _robots = RobotsCache(sf, UA, log=log)
    return _robots


def polite_get(url: str, *, params: Optional[dict] = None, headers: Optional[dict] = None,
               timeout: tuple = (20, 120)) -> requests.Response:
    global _last
    full = url if not params else f"{url}?{urlencode(params)}"
    if not robots().can_fetch(full.split("?")[0] if "/datosabiertos/" in url else full):
        # Check path without query for API; with query for search-like URLs
        if not robots().can_fetch(url):
            raise PermissionError(f"robots.txt disallows {url}")
    wait = MIN_DELAY - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    for attempt in range(6):
        _last = time.time()
        r = session().get(url, params=params, headers=headers, timeout=timeout)
        if r.status_code in (429, 500, 502, 503, 504):
            ra = r.headers.get("Retry-After")
            time.sleep(float(ra) if ra and ra.isdigit() else min(60, 2 ** attempt))
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r


def xml_to_text(xml: str) -> str:
    # Strip response envelope noise; keep bloque body text
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", xml)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</li>|</tr>|</bloque>", "\n", h)
    t = _html.unescape(re.sub(r"<[^>]+>", " ", h))
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def norm_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    d = re.sub(r"\D", "", s)
    if len(d) >= 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    if len(d) == 6:
        return f"{d[:4]}-{d[4:6]}"
    if len(d) == 4:
        return d
    return None


def region_of(item: dict) -> Optional[str]:
    m = re.search(r"/eli/es-([a-z]{2})/", item.get("url_eli") or "", re.I)
    if m:
        code = m.group(1).upper()
        if code in CCAA_ISO:
            return code
    name = ((item.get("departamento") or {}).get("texto") or "").lower()
    for k, v in CCAA_BY_NAME:
        if k in name:
            return v
    return None


def doc_type_of(rango: str) -> str:
    r = (rango or "").lower()
    if re.search(r"^(ley|real decreto[- ]ley|real decreto legislativo|decreto[- ]ley|"
                 r"decreto legislativo|constituci|estatuto)", r):
        return "statute"
    return "regulation"


def atomic_write(path: Path, rows: list[dict], validate_pk: Optional[str] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = (path.with_name("." + path.name[:-len(".jsonl")] + ".tmp.jsonl")
           if path.suffix == ".jsonl" else path.with_name(path.name + ".tmp"))
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    if validate_pk and validate_file:
        v = validate_file(tmp, expect_place_key=validate_pk)
        if not v["ok"]:
            raise RuntimeError(f"validate_file failed for {path.name}: {v['errors'][:3]} {v['file_errors']}")
    os.rename(tmp, path)


def flush_batch(bno: int, rows: list[dict], done_f) -> dict:
    ts = utc_tag()
    tag = f"esboe_ac_{ts}p0001"
    by_place: dict[str, list] = defaultdict(list)
    unmatched: list[dict] = []
    for r in rows:
        (by_place[r["place_id"]] if r.get("place_id") else unmatched).append(r)
    stats = Counter()
    for pid, rs in by_place.items():
        d = OUT / rs[0]["country_code"]
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{schema_place_key(pid)}.{tag}.jsonl"
        if validate_record:
            bad = {r["doc_id"]: e for r in rs for e in [validate_record(r)] if e}
            if bad:
                log.warning("%s: %d invalid -> _invalid/", p.name, len(bad))
                INV_DIR.mkdir(parents=True, exist_ok=True)
                atomic_write(INV_DIR / p.name, [dict(r, _errors=bad[r["doc_id"]]) for r in rs if r["doc_id"] in bad])
                rs = [r for r in rs if r["doc_id"] not in bad]
                if not rs:
                    continue
        atomic_write(p, rs, validate_pk=schema_place_key(pid) if validate_file else None)
        stats["matched"] += len(rs)
    if unmatched:
        atomic_write(UNM_DIR / f"esboe_ac_unmatched_{ts}p0001.jsonl", unmatched)
        stats["unmatched"] += len(unmatched)
    for r in rows:
        done_f.write(r["doc_id"] + "\n")
    done_f.flush()
    os.fsync(done_f.fileno())
    return stats


def discover() -> Path:
    STATE.mkdir(parents=True, exist_ok=True)
    cat = STATE / "catalog.jsonl"
    meta_p = STATE / "discover.json"
    tmp = cat.with_suffix(".tmp")
    off = 0
    n = 0
    regions: Counter = Counter()
    unmatched_reg = 0
    with tmp.open("w", encoding="utf-8") as out:
        while True:
            r = polite_get(
                API,
                params={"limit": 500, "offset": off, "query": QUERY_AC},
                headers={"Accept": "application/json"},
            )
            data = (r.json() or {}).get("data") or []
            if not data:
                break
            for it in data:
                if (it.get("ambito") or {}).get("codigo") != "2":
                    continue
                reg = region_of(it)
                if reg:
                    regions[reg] += 1
                else:
                    unmatched_reg += 1
                out.write(json.dumps(it, ensure_ascii=False) + "\n")
                n += 1
            off += len(data)
            log.info("discover listed offset=%d catalog=%d", off, n)
            if len(data) < 500:
                break
    os.rename(tmp, cat)
    meta = {
        "at": utcnow(), "catalog_n": n, "api_offset": off, "regions": dict(regions),
        "no_region": unmatched_reg, "query": QUERY_AC, "api": API,
    }
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    log.info("discover done n=%d regions=%s no_region=%d", n, dict(regions), unmatched_reg)
    return cat


def build_record(it: dict, text: str) -> dict:
    did = it["identificador"]
    reg = region_of(it)
    rango = ((it.get("rango") or {}).get("texto") or "")
    dep = (it.get("departamento") or {}).get("texto")
    src = it.get("url_html_consolidada") or f"https://www.boe.es/buscar/act.php?id={did}"
    # Prefer allowed API/document URLs for provenance; human HTML act.php is allowed by robots.
    rec = {
        "place_id": f"iso:ES-{reg}" if reg else None,
        "country_code": "ES",
        "doc_id": did,
        "source_platform": "es_boe_ac",
        "source_url": src,
        "doc_type": doc_type_of(rango),
        "language": "es",
        "title_native": it.get("titulo"),
        "number": it.get("numero_oficial"),
        "adopted_date": norm_date(it.get("fecha_disposicion")),
        "published_date": norm_date(it.get("fecha_publicacion")),
        "effective_date": norm_date(it.get("fecha_vigencia")),
        "in_force": {"N": True, "S": False}.get(it.get("vigencia_agotada")),
        "consolidated": True,
        "content_format": "xml",
        "text": text,
        "retrieved_at": utcnow(),
        "admin_level": "adm1" if reg else None,
        "iso_3166_2": f"ES-{reg}" if reg else None,
        "place_name": CCAA_NAMES.get(reg, dep) if reg else dep,
        "platform": "es_boe_ac",
        "platform_place_id": reg,
        "source_policy": "robots_allowed_rfc9309",
        "extra_metadata": {
            "ambito": it.get("ambito"),
            "departamento": it.get("departamento"),
            "rango": it.get("rango"),
            "url_eli": it.get("url_eli"),
            "estado_consolidacion": it.get("estado_consolidacion"),
            "fecha_actualizacion": it.get("fecha_actualizacion"),
            "api_texto": f"{API}/id/{did}/texto",
            "place_match": f"eli_or_departamento->{reg}" if reg else "unmatched_ccaa",
        },
    }
    return rec


def fetch(*, limit: Optional[int] = None) -> None:
    for d in (ES_DIR, UNM_DIR, STATE, RAW_DIR):
        d.mkdir(parents=True, exist_ok=True)
    cat = STATE / "catalog.jsonl"
    if not cat.exists():
        discover()
    done_path = STATE / "done.txt"
    done = set(done_path.read_text().split()) if done_path.exists() else set()
    failed_path = STATE / "failed.jsonl"
    bstate = STATE / "batchno.txt"
    bno = int(bstate.read_text()) if bstate.exists() else 0
    n_all = sum(1 for _ in cat.open(encoding="utf-8"))
    todo_n = n_all - len(done)
    if limit:
        todo_n = min(todo_n, limit)
    log.info("fetch catalog=%d done=%d todo=%d next_batch=%d", n_all, len(done), todo_n, bno + 1)

    rows: list[dict] = []
    rbytes = 0
    tot = Counter()
    t0 = time.time()
    i = 0
    with done_path.open("a", encoding="utf-8") as done_f, failed_path.open("a", encoding="utf-8") as fail_f:
        with cat.open(encoding="utf-8") as f:
            for ln in f:
                it = json.loads(ln)
                did = it["identificador"]
                if did in done:
                    continue
                i += 1
                if limit and i > limit:
                    break
                texto_url = f"{API}/id/{did}/texto"
                raw = RAW_DIR / f"{did}.xml.gz"
                try:
                    if raw.exists():
                        import gzip
                        xml = gzip.decompress(raw.read_bytes()).decode("utf-8", "replace")
                    else:
                        if not robots().can_fetch(texto_url):
                            raise PermissionError(f"robots disallows {texto_url}")
                        xml = polite_get(texto_url, headers={"Accept": "application/xml"}).text
                        import gzip
                        raw.write_bytes(gzip.compress(xml.encode("utf-8")))
                    text = xml_to_text(xml)
                    del xml
                    rec = build_record(it, text)
                    rows.append(rec)
                    rbytes += len(text)
                except Exception as e:  # noqa: BLE001
                    log.warning("FAIL %s: %s", did, e)
                    fail_f.write(json.dumps({"doc_id": did, "error": str(e)[:500], "at": utcnow()}) + "\n")
                    fail_f.flush()
                    # do not mark done — retry later
                    continue
                if len(rows) >= BATCH_DOCS or rbytes >= BATCH_BYTES or (limit and i >= limit):
                    bno += 1
                    s = flush_batch(bno, rows, done_f)
                    bstate.write_text(str(bno))
                    tot.update(s)
                    for r in rows:
                        done.add(r["doc_id"])
                    rows, rbytes = [], 0
                    gc.collect()
                    rate = i / max(time.time() - t0, 1)
                    log.info(
                        "batch %04d matched=%d unmatched=%d | %d/%d (%.2f doc/s)",
                        bno, s["matched"], s["unmatched"], i, todo_n, rate,
                    )
        if rows:
            bno += 1
            tot.update(flush_batch(bno, rows, done_f))
            bstate.write_text(str(bno))
    log.info("fetch finished: %s", dict(tot))


def status() -> None:
    meta = STATE / "discover.json"
    print("discover:", meta.read_text() if meta.exists() else None)
    dp = STATE / "done.txt"
    print("done docs:", len(dp.read_text().split()) if dp.exists() else 0)
    cat = STATE / "catalog.jsonl"
    print("catalog:", sum(1 for _ in cat.open()) if cat.exists() else 0)
    places: Counter = Counter()
    for p in ES_DIR.glob("iso_ES-*.esboe_ac_*.jsonl"):
        for ln in p.open(encoding="utf-8"):
            places[json.loads(ln)["place_id"]] += 1
    unm = 0
    for p in UNM_DIR.glob("esboe_ac_unmatched_*.jsonl"):
        unm += sum(1 for _ in p.open())
    print(f"matched docs={sum(places.values())} places={len(places)} unmatched={unm}")
    for k, v in places.most_common():
        print(f"  {v:5d} {k}")
    # Sanity: es_ine crosswalk loaded for ES municipal codes (not used for AC iso places)
    sample = XWALK.get("ES", "28079")  # Madrid municipio if present
    print("xwalk es_ine sample 28079 ->", sample)


def main() -> None:
    ap = argparse.ArgumentParser(description="Spain BOE autonomous-community consolidada (EU lane)")
    ap.add_argument("cmd", choices=["discover", "fetch", "all", "status"])
    ap.add_argument("--limit", type=int, help="fetch at most N docs")
    ap.add_argument("--test", type=int, help="fetch N docs into staging/eu/_test_es/")
    a = ap.parse_args()
    setup_logging()
    if a.test:
        global OUT, ES_DIR, UNM_DIR, STATE, RAW_DIR, INV_DIR
        OUT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/_test_es"))
        ES_DIR = OUT / "ES"
        UNM_DIR = OUT / "_unmatched"
        STATE = OUT / "_state"
        RAW_DIR = OUT / "_raw"
        INV_DIR = OUT / "_invalid"
        for d in (ES_DIR, UNM_DIR, STATE):
            d.mkdir(parents=True, exist_ok=True)
        src = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/_state/es_boe_ac/catalog.jsonl"))
        if not src.exists():
            # discover into real state then sample
            real_state = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/_state/es_boe_ac"))
            real_state.mkdir(parents=True, exist_ok=True)
            # temporarily point STATE for discover
            old = STATE
            # run discover into production state
            globals()["STATE"] = real_state
            discover()
            STATE = old
            src = real_state / "catalog.jsonl"
        lines = src.read_text(encoding="utf-8").splitlines()
        import random
        random.seed(7)
        sample = random.sample(lines, min(a.test, len(lines)))
        (STATE / "catalog.jsonl").write_text("\n".join(sample) + "\n", encoding="utf-8")
        return fetch(limit=a.test)
    log.info("start %s pid=%d", a.cmd, os.getpid())
    if a.cmd == "status":
        return status()
    if a.cmd in ("discover", "all"):
        discover()
    if a.cmd in ("fetch", "all"):
        fetch(limit=a.limit)


if __name__ == "__main__":
    main()
