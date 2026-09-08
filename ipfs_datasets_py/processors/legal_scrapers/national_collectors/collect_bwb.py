#!/usr/bin/env python3
"""Collect in-force Dutch national legislation (BWB / wetten.overheid.nl).

Official sources:
  - SRU: https://zoekservice.overheid.nl/sru/Search?x-connection=BWB
  - Repository: https://repository.officiele-overheidspublicaties.nl/bwb/{id}/
  - Human: https://wetten.overheid.nl/
License as stated by KOOP on data.overheid.nl: CC-0 (1.0).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree as ET

import requests
from requests.adapters import HTTPAdapter

ROOT = Path("/workspace/legal-corpora/nl")
INSTR_DIR = ROOT / "instruments"
LOG_DIR = ROOT / "logs"
INDEX_PATH = ROOT / "index.jsonl"
SUMMARY_PATH = ROOT / "SUMMARY.md"
CATALOG_PATH = LOG_DIR / "sru_catalog.jsonl"
FAILED_PATH = LOG_DIR / "failed.jsonl"
LOG_PATH = LOG_DIR / "collector.log"

SRU_URL = "https://zoekservice.overheid.nl/sru/Search"
VALID_ON = "2026-09-02"  # collection date (UTC calendar date of run start)
UA = (
    "NL-BWB-legal-corpus-collector/1.0 "
    "(research archive of CC-0 BWB; polite; "
    "source=https://wetten.overheid.nl/)"
)
LICENSE = (
    "CC0-1.0 as stated by KOOP on data.overheid.nl dataset "
    "'Basis Wetten Bestand' (https://data.overheid.nl/dataset/basis-wetten-bestand): "
    "Alle regelingen uit het basiswettenbestand zijn als open data beschikbaar in XML-formaat; "
    "license CC-0 (1.0). Database freely available (SRU explain restrictions)."
)
PUBLISHER = "KOOP/overheid.nl"
SOURCE_NAME = "wetten.overheid.nl"
# Treaties are international instruments in BWB (typically BWBV), not national wet/AMvB/regeling.
EXCLUDE_TYPES = {"verdrag", "verdrag-met-protocol", "internationale-regelgeving"}

PAGE_SIZE = 200
MAX_WORKERS = 8
HTTP_TIMEOUT = (15, 90)
RETRIES = 5

SKIP_XML_TAGS = {
    "meta-data",
    "brondata",
    "oorspronkelijk",
    "inwerkingtreding",
    "jcis",
    "jci",
    "bwb-inputbestand",
    "bwb-wijzigingen",
    "redactionele-correcties",
    "publicatie",
    "publicatiejaar",
    "publicatienr",
    "ondertekeningsdatum",
    "inwerkingtreding.datum",
    "dossierref",
    "uitgiftedatum",
    "redactie",
    "extref",
}
BLOCK_XML_TAGS = {
    "artikel",
    "lid",
    "hoofdstuk",
    "titeldeel",
    "afdeling",
    "paragraaf",
    "subparagraaf",
    "wet-besluit",
    "regeling",
    "bijlage",
    "circulaire",
    "intitule",
    "citeertitel",
    "aanhef",
    "considerans",
    "considerans.al",
    "slotformulier",
    "ondertekening",
    "toelichting",
    "nota-toelichting",
    "kop",
    "divisie",
    "al",
    "li",
    "lijst",
    "tussenkop",
}

_index_lock = threading.Lock()
_fail_lock = threading.Lock()
_log_lock = threading.Lock()
_tls = threading.local()


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def localtag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    INSTR_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    # Force UTC-ish timestamps in FileHandler via asctime of local; box is UTC.
    logging.Formatter.converter = time.gmtime


def get_session() -> requests.Session:
    s = getattr(_tls, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept": "application/xml, text/xml, */*"})
        ad = HTTPAdapter(pool_connections=MAX_WORKERS, pool_maxsize=MAX_WORKERS)
        s.mount("https://", ad)
        s.mount("http://", ad)
        _tls.session = s
    return s


def http_get(url: str, params: Optional[dict] = None, ok_status: tuple = (200, 406)) -> requests.Response:
    last_err: Optional[Exception] = None
    for attempt in range(1, RETRIES + 1):
        try:
            r = get_session().get(url, params=params, timeout=HTTP_TIMEOUT)
            if r.status_code in ok_status:
                return r
            if r.status_code in (404, 410):
                r.raise_for_status()
            if r.status_code in (429, 500, 502, 503, 504) or r.status_code not in ok_status:
                last_err = RuntimeError(f"HTTP {r.status_code} for {url}")
                wait = min(2 ** attempt, 32)
                logging.warning("retry %s/%s HTTP %s %s wait=%ss", attempt, RETRIES, r.status_code, url, wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last_err = e
            wait = min(2 ** attempt, 32)
            logging.warning("retry %s/%s error %s %s wait=%ss", attempt, RETRIES, e, url, wait)
            time.sleep(wait)
    raise last_err or RuntimeError(f"failed GET {url}")


def text_of(elem: ET.Element) -> str:
    parts: list[str] = []

    def rec(e: ET.Element) -> None:
        tag = localtag(e.tag)
        if tag in SKIP_XML_TAGS:
            return
        if tag in BLOCK_XML_TAGS:
            parts.append("\n")
        if e.text and e.text.strip():
            parts.append(e.text.strip())
        for c in list(e):
            rec(c)
            if c.tail and c.tail.strip():
                parts.append(c.tail.strip())
        if tag in BLOCK_XML_TAGS:
            parts.append("\n")

    rec(elem)
    raw = " ".join(parts)
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n[ \t]+", "\n", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def first_attr_or_text(root: ET.Element, local_names: set[str]) -> Optional[str]:
    for e in root.iter():
        if localtag(e.tag) in local_names:
            if e.text and e.text.strip():
                return e.text.strip()
    return None


def extract_date_issued(root: ET.Element) -> Optional[str]:
    # Prefer original signature date, then inwerkingtreding on wetgeving/toestand.
    for e in root.iter():
        if localtag(e.tag) == "ondertekeningsdatum":
            iso = e.attrib.get("isodatum")
            if iso:
                return iso
            if e.text and re.match(r"\d{4}-\d{2}-\d{2}", e.text.strip()):
                return e.text.strip()
    for attr in ("inwerkingtredingsdatum", "inwerkingtreding"):
        v = root.attrib.get(attr)
        if v:
            return v
        for e in root.iter():
            if attr in e.attrib:
                return e.attrib[attr]
    return None


def parse_sru_records(xml_bytes: bytes) -> tuple[int, list[dict[str, Any]]]:
    root = ET.fromstring(xml_bytes)
    nrec = 0
    for e in root.iter():
        if localtag(e.tag) == "numberOfRecords" and e.text:
            nrec = int(e.text)
            break
    out: list[dict[str, Any]] = []
    for rec in root.iter():
        if localtag(rec.tag) != "record":
            continue
        data: dict[str, Any] = {
            "id": None,
            "title": None,
            "type": None,
            "language": "nl",
            "authority": None,
            "creator": None,
            "modified": None,
            "created": None,
            "toestand": None,
            "locatie_toestand": None,
            "locatie_wti": None,
            "locatie_manifest": None,
            "geldig_van": None,
            "geldig_tot": None,
            "rechtsgebieden": [],
        }
        for e in rec.iter():
            tag = localtag(e.tag)
            val = (e.text or "").strip() if e.text else ""
            if tag == "identifier" and val and not data["id"]:
                data["id"] = val
            elif tag == "title" and val and not data["title"]:
                data["title"] = val
            elif tag == "type" and val and not data["type"]:
                data["type"] = val
            elif tag == "language" and val:
                data["language"] = val
            elif tag == "authority" and val and not data["authority"]:
                data["authority"] = val
            elif tag == "creator" and val and not data["creator"]:
                data["creator"] = val
            elif tag == "modified" and val and not data["modified"]:
                data["modified"] = val
            elif tag == "created" and val and not data["created"]:
                data["created"] = val
            elif tag == "toestand" and val and not data["toestand"]:
                data["toestand"] = val
            elif tag == "locatie_toestand" and val:
                data["locatie_toestand"] = val
            elif tag == "locatie_wti" and val:
                data["locatie_wti"] = val
            elif tag == "locatie_manifest" and val:
                data["locatie_manifest"] = val
            elif tag == "geldigheidsperiode_startdatum" and val and not data["geldig_van"]:
                data["geldig_van"] = val
            elif tag == "geldigheidsperiode_einddatum" and val and not data["geldig_tot"]:
                data["geldig_tot"] = val
            elif tag == "rechtsgebied" and val:
                data["rechtsgebieden"].append(val)
        if data["id"]:
            out.append(data)
    return nrec, out


def discover_catalog(force: bool = False) -> list[dict[str, Any]]:
    if CATALOG_PATH.exists() and not force and CATALOG_PATH.stat().st_size > 0:
        rows = []
        with CATALOG_PATH.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        logging.info("Loaded existing SRU catalog: %s rows from %s", len(rows), CATALOG_PATH)
        if rows:
            return rows

    logging.info("Discovering in-force BWB via SRU geldigheidsdatum=%s page_size=%s", VALID_ON, PAGE_SIZE)
    start = 1
    total_declared = None
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    tmp = CATALOG_PATH.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as out:
        while True:
            params = {
                "operation": "searchRetrieve",
                "version": "2.0",
                "x-connection": "BWB",
                "maximumRecords": str(PAGE_SIZE),
                "startRecord": str(start),
                "query": f"overheidbwb.geldigheidsdatum={VALID_ON}",
            }
            r = http_get(SRU_URL, params=params)
            nrec, recs = parse_sru_records(r.content)
            if total_declared is None:
                total_declared = nrec
                logging.info("SRU numberOfRecords (in-force toestanden) = %s", nrec)
            if not recs:
                logging.info("SRU empty page at startRecord=%s; stopping", start)
                break
            for rec in recs:
                bid = rec["id"]
                if bid in seen:
                    continue
                seen.add(bid)
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                rows.append(rec)
            logging.info(
                "SRU page start=%s got=%s unique_so_far=%s declared=%s",
                start,
                len(recs),
                len(rows),
                total_declared,
            )
            start += len(recs)
            if total_declared is not None and start > total_declared:
                break
            if len(recs) < PAGE_SIZE:
                break
            time.sleep(0.15)
    os.replace(tmp, CATALOG_PATH)
    logging.info("Wrote catalog %s (%s unique identifiers, declared %s)", CATALOG_PATH, len(rows), total_declared)
    return rows


def load_done_ids() -> set[str]:
    done: set[str] = set()
    if not INDEX_PATH.exists():
        return done
    with INDEX_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("status") == "ok" and obj.get("id"):
                done.add(obj["id"])
    return done


def append_jsonl(path: Path, obj: dict[str, Any], lock: threading.Lock) -> None:
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())


def safe_id(bwb_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", bwb_id)


def eli_for(rec: dict[str, Any]) -> Optional[str]:
    t = rec.get("toestand")
    if t:
        if t.startswith("http://"):
            return "https://" + t[len("http://") :]
        return t
    loc = rec.get("locatie_toestand") or ""
    m = re.search(r"/bwb/(BWB[A-Z]\d+)/(\d{4}-\d{2}-\d{2})_(\d+)/", loc)
    if m:
        return f"https://wetten.overheid.nl/id/{m.group(1)}/{m.group(2)}/{m.group(3)}"
    if rec.get("id"):
        return f"https://wetten.overheid.nl/id/{rec['id']}"
    return None


def source_url_for(rec: dict[str, Any]) -> str:
    t = rec.get("toestand") or ""
    m = re.search(r"/id/(BWB[A-Z]\d+)/(\d{4}-\d{2}-\d{2})/(\d+)", t)
    if m:
        return f"https://wetten.overheid.nl/{m.group(1)}/{m.group(2)}"
    if rec.get("id"):
        return f"https://wetten.overheid.nl/{rec['id']}"
    return "https://wetten.overheid.nl/"


def build_record(rec: dict[str, Any], xml_bytes: bytes, xml_url: str) -> dict[str, Any]:
    root = ET.fromstring(xml_bytes)
    body = text_of(root)
    title = rec.get("title") or first_attr_or_text(root, {"citeertitel", "intitule"}) or rec["id"]
    date_issued = extract_date_issued(root) or rec.get("created")
    retrieved = utcnow()
    bwb_id = rec["id"]
    src = source_url_for(rec)
    eli = eli_for(rec)
    doc_id = f"{bwb_id}:{rec.get('geldig_van') or 'current'}"
    record = {
        "id": bwb_id,
        "title": title,
        "jurisdiction": "NL",
        "country": "Netherlands",
        "language": rec.get("language") or "nl",
        "source_type": "national_legislation",
        "source_url": src,
        "eli": eli,
        "date_issued": date_issued,
        "text": body,
        "documents": [
            {
                "id": doc_id,
                "title": title,
                "text": body,
                "source_url": xml_url,
                "metadata": {
                    "format": "application/xml",
                    "bwb_type": rec.get("type"),
                    "toestand": rec.get("toestand"),
                    "geldig_van": rec.get("geldig_van"),
                    "geldig_tot": rec.get("geldig_tot"),
                    "locatie_toestand": rec.get("locatie_toestand"),
                    "locatie_wti": rec.get("locatie_wti"),
                    "locatie_manifest": rec.get("locatie_manifest"),
                    "bytes_xml": len(xml_bytes),
                },
            }
        ],
        "metadata": {
            "license": LICENSE,
            "retrieved_at": retrieved,
            "official_id": bwb_id,
            "publisher": PUBLISHER,
            "source_name": SOURCE_NAME,
            "bwb_type": rec.get("type"),
            "authority": rec.get("authority"),
            "creator": rec.get("creator"),
            "modified": rec.get("modified"),
            "created": rec.get("created"),
            "geldig_van": rec.get("geldig_van"),
            "geldig_tot": rec.get("geldig_tot"),
            "rechtsgebieden": rec.get("rechtsgebieden") or [],
            "valid_on": VALID_ON,
            "in_force": True,
        },
    }
    return record


def fetch_one(rec: dict[str, Any]) -> dict[str, Any]:
    bwb_id = rec["id"]
    xml_url = rec.get("locatie_toestand")
    if not xml_url:
        raise RuntimeError("missing locatie_toestand")
    r = http_get(xml_url, ok_status=(200,))
    if not r.content or len(r.content) < 50:
        raise RuntimeError(f"empty/short XML ({len(r.content)} bytes)")
    record = build_record(rec, r.content, xml_url)
    sid = safe_id(bwb_id)
    path = INSTR_DIR / f"{sid}.json"
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with tmp.open("w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    nbytes = path.stat().st_size
    idx = {
        "id": bwb_id,
        "title": record["title"],
        "path": str(path.relative_to(ROOT)),
        "source_url": record["source_url"],
        "eli": record["eli"],
        "bwb_type": rec.get("type"),
        "bytes": nbytes,
        "status": "ok",
        "retrieved_at": record["metadata"]["retrieved_at"],
    }
    append_jsonl(INDEX_PATH, idx, _index_lock)
    return idx


def record_failure(rec: dict[str, Any], err: str) -> None:
    obj = {
        "id": rec.get("id"),
        "title": rec.get("title"),
        "type": rec.get("type"),
        "locatie_toestand": rec.get("locatie_toestand"),
        "error": err,
        "status": "failed",
        "retrieved_at": utcnow(),
    }
    append_jsonl(FAILED_PATH, obj, _fail_lock)
    append_jsonl(INDEX_PATH, {**obj, "bytes": 0}, _index_lock)
    logging.error("FAILED %s: %s", rec.get("id"), err)


def is_national(rec: dict[str, Any]) -> bool:
    bid = rec.get("id") or ""
    typ = (rec.get("type") or "").strip()
    if typ in EXCLUDE_TYPES:
        return False
    if bid.startswith("BWBV"):
        return False
    return bid.startswith("BWBR") or bid.startswith("BWB")


def write_summary(
    listed_inforce: int,
    listed_national: int,
    collected: int,
    failed: int,
    skipped_existing: int,
    excluded_treaties: int,
    type_listed: dict[str, int],
    type_collected: dict[str, int],
    bytes_total: int,
    started: str,
    finished: str,
    blockers: list[str],
) -> None:
    lines = [
        "# Dutch national legislation corpus (BWB / wetten.overheid.nl)",
        "",
        f"- Generated: {finished} (UTC); user timezone America/Los_Angeles (PT = UTC-7)",
        f"- Collection window started: {started}",
        f"- In-force date (overheidbwb.geldigheidsdatum): {VALID_ON}",
        f"- Output root: `{ROOT}`",
        "",
        "## Official sources",
        "",
        "- Human interface: https://wetten.overheid.nl/",
        "- SRU (identifier list + current toestand locations): https://zoekservice.overheid.nl/sru/Search?x-connection=BWB",
        "- XML repository: https://repository.officiele-overheidspublicaties.nl/bwb/{BWB-id}/",
        "- FRBR/repository note: https://repository.overheid.nl/frbr/bwb (not used; 404 at harvest time)",
        "- Linked data: https://linkeddata.overheid.nl/",
        "- Dataset landing: https://data.overheid.nl/dataset/basis-wetten-bestand",
        "- How to build a copy: https://www.overheid.nl/help/wet-en-regelgeving/een-eigen-kopie-van-het-basiswettenbestand-opbouwen",
        "",
        "## License / reuse (as stated by the publisher)",
        "",
        f"- {LICENSE}",
        "- SRU explain: “Database is freely available”.",
        "- Publisher: KOOP (Kennis- en Exploitatiecentrum voor Officiële Overheidspublicaties) / overheid.nl",
        "",
        "## Scope",
        "",
        "Full **in-force** national BWB corpus as returned by the official SRU service for today's geldigheidsdatum.",
        "Each SRU hit is one current *toestand* (consolidated version) of a regeling.",
        "Treaties (`dcterms.type=verdrag`, typically BWBV) are listed in discovery but **excluded** from instruments/",
        "because they are international instruments, not national wet/AMvB/regeling.",
        "No git clone; records streamed to disk; resume via index.jsonl.",
        "",
        "## Counts",
        "",
        f"- Listed in-force toestanden (SRU numberOfRecords / unique ids discovered): **{listed_inforce}**",
        f"- Listed in-force national (BWBR wet/AMvB/regeling etc., treaties excluded): **{listed_national}**",
        f"- Excluded treaties (verdrag): **{excluded_treaties}**",
        f"- Collected OK (instruments/*.json): **{collected}**",
        f"- Failed: **{failed}**",
        f"- Skipped already present on resume: **{skipped_existing}**",
        f"- Bytes of instruments JSON on disk: **{bytes_total}** ({bytes_total / (1024*1024):.1f} MiB)",
        "",
        "### Listed by dcterms.type (all in-force, including treaties)",
        "",
    ]
    for k, v in sorted(type_listed.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- {k or '(none)'}: {v}")
    lines += [
        "",
        "### Collected by dcterms.type",
        "",
    ]
    for k, v in sorted(type_collected.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- {k or '(none)'}: {v}")
    lines += [
        "",
        "## Outputs",
        "",
        "- `instruments/{BWBR}.json` — one record per in-force national instrument",
        "- `index.jsonl` — stream of collected/failed rows (resume checkpoint)",
        "- `logs/sru_catalog.jsonl` — full SRU discovery dump (all in-force ids)",
        "- `logs/failed.jsonl` — failures with error text",
        "- `logs/collector.log` — run log",
        "",
        "## Blockers",
        "",
    ]
    if blockers:
        for b in blockers:
            lines.append(f"- {b}")
    else:
        lines.append("- None.")
    lines += [
        "",
        "## Method",
        "",
        "1. SRU explain reported collection “BWB Repository”, lastUpdate 2026-09-02.",
        "2. Paginated `overheidbwb.geldigheidsdatum={valid_on}` with maximumRecords=200.",
        "3. Downloaded current toestand XML from `overheidbwb:locatie_toestand` (official repository).",
        "4. Extracted plain text from BWB toestand XML (skipping meta-data/JCI apparatus).",
        "5. Wrote JSON records adapted from Endomorphosis/ipfs_datasets_py legal_data ingest shape.",
        "",
    ]
    SUMMARY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logging.info("Wrote %s", SUMMARY_PATH)


def dir_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for p in path.glob("*.json"):
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="collect at most N national instruments (0=all)")
    ap.add_argument("--workers", type=int, default=MAX_WORKERS)
    ap.add_argument("--rediscover", action="store_true")
    args = ap.parse_args()
    setup_logging()
    started = utcnow()
    logging.info("=== BWB collector start %s valid_on=%s workers=%s ===", started, VALID_ON, args.workers)

    blockers: list[str] = []
    try:
        catalog = discover_catalog(force=args.rediscover)
    except Exception as e:
        logging.exception("Discovery failed")
        blockers.append(f"SRU discovery failed: {e}")
        write_summary(0, 0, 0, 0, 0, 0, {}, {}, 0, started, utcnow(), blockers)
        return 2

    type_listed: dict[str, int] = {}
    for rec in catalog:
        type_listed[rec.get("type") or ""] = type_listed.get(rec.get("type") or "", 0) + 1

    national = [r for r in catalog if is_national(r)]
    treaties = [r for r in catalog if not is_national(r)]
    logging.info("Catalog unique=%s national=%s treaties/excluded=%s", len(catalog), len(national), len(treaties))

    if args.limit and args.limit > 0:
        national = national[: args.limit]
        logging.info("LIMIT active: will collect %s", len(national))

    done = load_done_ids()
    todo = [r for r in national if r["id"] not in done]
    skipped = len(national) - len(todo)
    logging.info("Resume: already_ok=%s todo=%s", skipped, len(todo))

    collected_now = 0
    failed_now = 0
    type_collected: dict[str, int] = {}

    # Count already collected types from index
    if INDEX_PATH.exists():
        with INDEX_PATH.open(encoding="utf-8") as f:
            for line in f:
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if o.get("status") == "ok":
                    t = o.get("bwb_type") or ""
                    type_collected[t] = type_collected.get(t, 0) + 1

    def _work(rec: dict[str, Any]) -> tuple[str, Optional[dict], Optional[str]]:
        try:
            idx = fetch_one(rec)
            return rec["id"], idx, None
        except Exception as e:
            return rec["id"], None, f"{type(e).__name__}: {e}"

    workers = max(1, args.workers)
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_work, rec): rec for rec in todo}
            n = 0
            for fut in as_completed(futs):
                rec = futs[fut]
                n += 1
                try:
                    _id, idx, err = fut.result()
                except Exception as e:
                    err = f"{type(e).__name__}: {e}"
                    idx = None
                    _id = rec.get("id")
                if err:
                    failed_now += 1
                    record_failure(rec, err)
                else:
                    collected_now += 1
                    t = (idx or {}).get("bwb_type") or rec.get("type") or ""
                    type_collected[t] = type_collected.get(t, 0) + 1
                if n % 50 == 0 or n == len(todo):
                    logging.info(
                        "progress %s/%s collected_now=%s failed_now=%s",
                        n,
                        len(todo),
                        collected_now,
                        failed_now,
                    )
                if n % 500 == 0:
                    # periodic summary so a killed run still has numbers
                    b = dir_bytes(INSTR_DIR)
                    write_summary(
                        listed_inforce=len(catalog),
                        listed_national=len([r for r in catalog if is_national(r)]),
                        collected=sum(1 for _ in INSTR_DIR.glob("*.json")),
                        failed=failed_now,
                        skipped_existing=skipped,
                        excluded_treaties=len(treaties),
                        type_listed=type_listed,
                        type_collected=type_collected,
                        bytes_total=b,
                        started=started,
                        finished=utcnow(),
                        blockers=blockers + ["Run still in progress (periodic SUMMARY)."],
                    )

    # Final counts from disk + index
    collected_files = list(INSTR_DIR.glob("*.json"))
    collected = len(collected_files)
    failed_total = 0
    if FAILED_PATH.exists():
        with FAILED_PATH.open(encoding="utf-8") as f:
            failed_total = sum(1 for line in f if line.strip())
    bytes_total = dir_bytes(INSTR_DIR)

    listed_national = len([r for r in catalog if is_national(r)])
    if collected < listed_national and not args.limit:
        blockers.append(
            f"Collected {collected} < listed national {listed_national} "
            f"(failed={failed_total}, skipped_existing={skipped})."
        )
    if failed_total:
        blockers.append(f"{failed_total} instrument download/parse failures; see logs/failed.jsonl.")

    write_summary(
        listed_inforce=len(catalog),
        listed_national=listed_national,
        collected=collected,
        failed=failed_total,
        skipped_existing=skipped,
        excluded_treaties=len(treaties),
        type_listed=type_listed,
        type_collected=type_collected,
        bytes_total=bytes_total,
        started=started,
        finished=utcnow(),
        blockers=blockers,
    )
    logging.info(
        "=== done collected=%s failed=%s bytes=%s listed_national=%s ===",
        collected,
        failed_total,
        bytes_total,
        listed_national,
    )
    return 0 if not blockers else 1


if __name__ == "__main__":
    sys.exit(main())
