#!/usr/bin/env python3
"""NL CVDR (Centrale Voorziening Decentrale Regelgeving) scraper -- world_law EU lane.

Discovery : KOOP SRU 2.0  https://zoekservice.overheid.nl/sru/Search?x-connection=cvdr
            query overheidrg.datumGeldendOp=<VALID_ON>  (= versions in force on that date)
Full text : https://repository.officiele-overheidspublicaties.nl/cvdr/CVDR<n>/<v>/xml/CVDR<n>_<v>.xml
Output    : /workspace/world_law/staging/eu/NL/<place_key>.cvdr_bNNNN.jsonl  (SCHEMA.md v1 staging contract)
            /workspace/world_law/staging/eu/_unmatched/cvdr_unmatched_bNNNN.jsonl (no place_id; same fields)
            /workspace/world_law/staging/eu/_raw/cvdr/<CVDRn>/<id>.xml.gz  (raw XML)
State     : /workspace/world_law/staging/eu/_state/  (catalog + done ids; resumable)
Logs      : /workspace/world_law/staging/eu/logs/cvdr.log

Reuses text_of()/localtag() from ipfs_datasets_py national_collectors/collect_bwb.py (same KOOP XML family).

    python cvdr.py discover            # build/resume SRU catalog
    python cvdr.py fetch [--limit N]   # fetch full texts, write batches (resumes)
    python cvdr.py all                 # discover then fetch
    python cvdr.py status
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
import csv
import gc
import gzip
import importlib.util
import json
import logging
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree as ET

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
_schema = None


def get_schema():
    """Import the normalizer's schema.py lazily (it may be mid-edit by another bot); None if broken."""
    global _schema
    if _schema is None:
        try:
            import schema as _s  # noqa: E402
            _schema = _s
        except Exception as e:  # noqa: BLE001
            logging.getLogger("cvdr").warning("schema.py import failed (%s); using fallback place_key, no validation", e)
            return None
    return _schema


def schema_place_key(pid: str) -> str:
    s = get_schema()
    return s.place_key(pid) if s else pid.replace(":", "_")

# --- reuse ipfs_datasets_py BWB collector helpers (loaded by path to avoid heavy package __init__) ---
_BWB = Path("/workspace/ipfs_datasets_py/ipfs_datasets_py/processors/legal_scrapers/national_collectors/collect_bwb.py")
_spec = importlib.util.spec_from_file_location("collect_bwb", _BWB)
bwb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bwb)
# extend for CVDR XML (meta block is metadata, not text; extra structural tags)
bwb.SKIP_XML_TAGS |= {"meta", "owmskern", "owmsmantel", "cvdripm"}
bwb.BLOCK_XML_TAGS |= {"preambule", "regeling-tekst", "regeling-sluiting", "table",
                       "row", "entry", "p", "tekst", "toelichting", "artikelsgewijs", "algemeen",
                       "slotformulering", "dagtekening", "plaats", "functie", "naam", "wijzig-lid",
                       "wijzig-artikel", "kop", "titel"}
localtag = bwb.localtag


def text_of(elem) -> str:
    t = bwb.text_of(elem)
    t = re.sub(r"[ \t]+\n", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()

SRU_URL = "https://zoekservice.overheid.nl/sru/Search"
REPO = "https://repository.officiele-overheidspublicaties.nl/cvdr"
UA = ("world-municipal-law-research/1.0 (EU lane; endomorphosis/ipfs_datasets_py; "
      "open-data reuse of CVDR per overheid.nl 'Informatie hergebruiken'; ~1.5 req/s)")
OUT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu"))
NL_DIR = OUT / "NL"
UNM_DIR = OUT / "_unmatched"
RAW_DIR = OUT / "_raw" / "cvdr"
STATE = OUT / "_state"
LOGS = OUT / "_logs"
PAGE = 1000
MIN_INTERVAL = 0.65     # seconds between requests (~1.5 req/s)
RETRIES = 6
BATCH_DOCS = 1000
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
WD_CSV = HERE / "data" / "wd_nl_bodies.csv"
PROV_ISO = {"Groningen": "NL-GR", "Fryslân": "NL-FR", "Friesland": "NL-FR", "Drenthe": "NL-DR",
            "Overijssel": "NL-OV", "Flevoland": "NL-FL", "Gelderland": "NL-GE", "Utrecht": "NL-UT",
            "Noord-Holland": "NL-NH", "Zuid-Holland": "NL-ZH", "Zeeland": "NL-ZE",
            "Noord-Brabant": "NL-NB", "Limburg": "NL-LI"}
LEVEL = {"gemeente": "municipality", "provincie": "adm1", "waterschap": "water_board",
         "regionaalsamenwerkingsorgaan": "regional_cooperation", "caribischopenbaarlichaam": "caribbean_public_body",
         "anderopenbaarlichaam": "other_public_body", "deelgemeente": "submunicipality",
         "eilandgebied": "island_territory", "nederlandseantillen": "island_territory_former_antilles",
         "koninkrijksdeel": "kingdom_part"}

_last = [0.0]
sys.path.insert(0, str(HERE))
from common.rfc9309 import RobotsCache  # noqa: E402  RFC 9309 (wildcard-aware) robots matcher
from common.xwalk import XWALK, ADDITIONS  # noqa: E402  shared place-code crosswalk (preferred) + place_additions.csv
# zoekservice.overheid.nl robots.txt is 'Disallow: /'; the SRU listing is an accepted, documented exception
# (official KOOP reuse API, CC0) -- discovery only. Everything else is robots-gated.
ROBOTS_EXCEPTIONS = ("https://zoekservice.overheid.nl/sru/",)
_robots: Optional[RobotsCache] = None


def robots_ok(url: str) -> bool:
    global _robots
    if url.startswith(ROBOTS_EXCEPTIONS):
        return True
    if _robots is None:
        def sf(_base):
            s = requests.Session()
            s.headers.update({"User-Agent": UA})
            return s
        _robots = RobotsCache(sf, UA, log=log)
    return _robots.can_fetch(url)
VALID_TAG = [""]  # e.g. "20261010", set in fetch()
_sess: Optional[requests.Session] = None
log = logging.getLogger("cvdr")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def setup_logging() -> None:
    for d in (NL_DIR, UNM_DIR, RAW_DIR, STATE, LOGS):
        d.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S%z")
    log.setLevel(logging.INFO)
    if not log.handlers:
        for h in (logging.FileHandler(LOGS / "cvdr.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)):
            h.setFormatter(fmt)
            log.addHandler(h)


def http_get(url: str, params: Optional[dict] = None) -> requests.Response:
    global _sess
    if _sess is None:
        _sess = requests.Session()
        _sess.headers.update({"User-Agent": UA, "Accept": "application/xml, text/xml, */*"})
    err: Any = None
    for attempt in range(RETRIES):
        wait = MIN_INTERVAL - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        try:
            r = _sess.get(url, params=params, timeout=(15, 120))
            if r.status_code == 200:
                return r
            if r.status_code in (404, 410):
                r.raise_for_status()
            if r.status_code in (401, 403):
                log.error("BLOCKED? HTTP %s for %s", r.status_code, r.url)
            err = RuntimeError(f"HTTP {r.status_code} {r.url}")
            ra = r.headers.get("Retry-After")
            backoff = float(ra) if ra and ra.isdigit() else min(2 ** (attempt + 1), 120)
        except requests.HTTPError:
            raise
        except requests.RequestException as e:
            err, backoff = e, min(2 ** (attempt + 1), 120)
        log.warning("retry %d/%d %s; sleep %.0fs", attempt + 1, RETRIES, err, backoff)
        time.sleep(backoff)
    raise err


# ----------------------------------------------------------------------------- SRU
def _txt(e: ET.Element) -> str:
    return " ".join("".join(e.itertext()).split())


def parse_sru(xml: bytes) -> tuple[int, list[dict]]:
    root = ET.fromstring(xml)
    n = 0
    for e in root.iter():
        if localtag(e.tag) == "numberOfRecords":
            n = int(e.text or 0)
            break
        if localtag(e.tag) == "diagnostic":
            raise RuntimeError("SRU diagnostic: " + _txt(e))
    out = []
    for rec in root.iter():
        if localtag(rec.tag) != "recordData":
            continue
        d: dict[str, Any] = {}
        for e in rec.iter():
            t = localtag(e.tag)
            if len(e) or t in ("recordData", "gzd", "originalData", "enrichedData", "meta",
                               "owmskern", "owmsmantel", "cvdripm"):
                if t != "redactioneleToevoeging":
                    continue
            v = _txt(e)
            if not v:
                continue
            if t == "creator":
                d["creator"] = v
                d["creator_scheme"] = (e.get("scheme") or "").split(":")[-1]
            elif t in d:
                if not isinstance(d[t], list):
                    d[t] = [d[t]]
                d[t].append(v)
            else:
                d[t] = v
        if d.get("identifier"):
            out.append(d)
    return n, out


def discover(valid_on: str) -> Path:
    cat = STATE / f"catalog_{valid_on}.jsonl"
    st_path = STATE / f"discover_{valid_on}.json"
    st = json.loads(st_path.read_text()) if st_path.exists() else {"next": 1, "declared": None, "complete": False}
    if st.get("complete"):
        log.info("catalog complete: %s", cat)
        return cat
    seen = set()
    if cat.exists():
        with cat.open() as f:
            for line in f:
                seen.add(json.loads(line)["identifier"])
    q = f"overheidrg.datumGeldendOp={valid_on}"
    log.info("SRU discovery query=%r resume at startRecord=%s (have %d)", q, st["next"], len(seen))
    with cat.open("a", encoding="utf-8") as f:
        while True:
            r = http_get(SRU_URL, {"x-connection": "cvdr", "operation": "searchRetrieve", "version": "2.0",
                                   "query": q, "maximumRecords": PAGE, "startRecord": st["next"]})
            n, recs = parse_sru(r.content)
            st["declared"] = n
            new = 0
            for d in recs:
                if d["identifier"] in seen:
                    continue
                seen.add(d["identifier"])
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
                new += 1
            f.flush()
            st["next"] += len(recs)
            log.info("SRU page got=%d new=%d unique=%d declared=%d next=%d", len(recs), new, len(seen), n, st["next"])
            if not recs or st["next"] > n:
                break
            st_path.write_text(json.dumps(st))
    # completeness check; fill gaps by partitioning on organisatieType if paging was unstable
    if len(seen) < st["declared"]:
        log.warning("unique %d < declared %d: partitioned refill", len(seen), st["declared"])
        with cat.open("a", encoding="utf-8") as f:
            for ot in ("Gemeente", "Provincie", "Waterschap", "Regionaalsamenwerkingsorgaan",
                       "CaribischOpenbaarLichaam", "AnderOpenbaarLichaam"):
                start = 1
                while True:
                    r = http_get(SRU_URL, {"x-connection": "cvdr", "operation": "searchRetrieve", "version": "2.0",
                                           "query": f"{q} and organisatieType={ot}", "maximumRecords": PAGE,
                                           "startRecord": start})
                    n, recs = parse_sru(r.content)
                    for d in recs:
                        if d["identifier"] not in seen:
                            seen.add(d["identifier"])
                            f.write(json.dumps(d, ensure_ascii=False) + "\n")
                    start += len(recs)
                    if not recs or start > n:
                        break
        log.info("after refill unique=%d declared=%d", len(seen), st["declared"])
    st["complete"] = True
    st["unique"] = len(seen)
    st_path.write_text(json.dumps(st))
    return cat


# ----------------------------------------------------------------------------- places
def wnorm(s: str) -> str:
    """water-board name key: drop Waterschap/Hoogheemraadschap/Wetterskip prefixes, '&'->'en'."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("&", " en ")
    s = re.sub(r"^\s*(waterschap|hoogheemraadschap( van)?|wetterskip)\s+", "", s.strip())
    return re.sub(r"[^a-z0-9]+", "", s)


# merged water boards -> successor (wnorm keys): 2013 Vallei & Eem + Veluwe -> Vallei en Veluwe;
# 2014 Velt en Vecht + Regge en Dinkel -> Vechtstromen
WS_SUCC = {"valleieneem": "valleienveluwe", "veluwe": "valleienveluwe", "veltenvecht": "vechtstromen",
           "reggeendinkel": "vechtstromen"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\((gemeente|gem\.?|nl|nederland|[a-z]{1,3})\)", " ", s)
    s = re.sub(r"^(gemeente|provincie|waterschap|hoogheemraadschap)\s+", "", s.strip())
    return re.sub(r"[^a-z0-9]+", "", s)


class PlaceMap:
    def __init__(self) -> None:
        self.cand: dict[str, dict] = {}          # qid -> candidate row
        by_name: dict[str, set] = defaultdict(set)
        for r in csv.DictReader(CAND.open(encoding="utf-8")):
            if r["country_code"] != "NL":
                continue
            self.cand[r["qid"]] = r
        self.wd: dict[str, dict] = {}
        current, former = defaultdict(set), defaultdict(set)
        for r in csv.DictReader(WD_CSV.open(encoding="utf-8")):
            q = r["item"].rsplit("/", 1)[-1]
            r["qid"] = q
            self.wd[q] = r
            names = {r["nl"], r["en"], *(r["alts"] or "").split("|")}
            tgt = former if r["end"] else current
            for nm in names:
                if nm:
                    tgt[norm(nm)].add(q)
        for q, r in self.cand.items():
            current[norm(r["place_name"])].add(q)
            by_name[norm(r["place_name"])].add(q)
        self.current, self.former = current, former
        self.overrides = {norm(k): v for k, v in {"'s-Gravenhage": "Q36600", "Den Haag": "Q36600"}.items()}
        # former municipality -> successor (candidate qid): Wikidata P1366/P1365, then manual table
        self.successor: dict[str, str] = {}
        name2cand = {norm(r["place_name"]): q for q, r in self.cand.items() if r["admin_level"] == "municipality"}
        for fn, a, b in (("wd_nl_successors.csv", "item", "succ"), ("wd_nl_replaces.csv", "old", "succ")):
            fp = HERE / "data" / fn
            if fp.exists():
                for r in csv.DictReader(fp.open(encoding="utf-8")):
                    old, new = r[a].rsplit("/", 1)[-1], r[b].rsplit("/", 1)[-1]
                    if new in self.cand:
                        self.successor.setdefault(old, new)
        self.manual_succ: dict[str, Optional[str]] = {}
        mp = HERE / "data" / "nl_mergers_manual.csv"
        if mp.exists():
            for r in csv.DictReader(mp.open(encoding="utf-8")):
                self.manual_succ[norm(r["former"])] = name2cand.get(norm(r["successor"])) if r["successor"] else None
        # shared place_additions.csv (Frisian municipalities by CBS/name, 21 water boards by nl_tooi ws-code/name)
        self.add_by_name: dict[tuple, dict] = {}
        for r in ADDITIONS.rows("NL"):
            lvl = r.get("admin_level") or ""
            for nm in (r.get("name"), r.get("name_native")):
                if nm:
                    self.add_by_name.setdefault((lvl, wnorm(nm) if lvl == "water_board" else norm(nm)), r)
        self.cache: dict[tuple, dict] = {}

    def _from_addition(self, res: dict, r: dict, match: str) -> dict:
        code = r.get("official_code") or None
        res.update(place_id=r["place_id"], qid=(r.get("qid") or r["place_id"][3:] if r["place_id"].startswith("wd:") else r.get("qid")) or None,
                   place_name=r.get("name_native") or r.get("name"), iso_3166_2=r.get("iso_3166_2") or None,
                   match=match, cand_admin_level=r.get("admin_level") or None)
        if r.get("official_code_system") == "nl_tooi" and code:
            res["issuing_body_code"] = code
            res["nl_waterschapscode"] = code[2:] if code.lower().startswith("ws") else None
        elif r.get("official_code_system") == "nl_cbs_gemeente" and code:
            res["issuing_body_code"] = f"GM{code}"
        return res

    def resolve(self, name: str, scheme: str) -> dict:
        key = (name, scheme)
        if key in self.cache:
            return self.cache[key]
        level = LEVEL.get((scheme or "").lower(), (scheme or "unknown").lower())
        res = {"place_id": None, "qid": None, "level": level, "issuing_body_code": None,
               "iso_3166_2": None, "place_name": None, "match": None, "successor_qid": None, "country_code": "NL"}
        n = norm(name)
        sl = (scheme or "").lower()
        if sl == "koninkrijksdeel":
            cc = {"curacao": "CW", "sintmaarten": "SX", "aruba": "AW"}.get(n)
            if cc:
                res.update(place_id=f"iso:{cc}", country_code=cc, level="country", issuing_body_code=cc,
                           place_name=name, match="kingdom_part_iso")
            self.cache[key] = res
            return res
        if sl == "caribischopenbaarlichaam":
            q = next((qq for qq, r in self.cand.items() if norm(r["place_name"]) == n), None)
            if q:
                c = self.cand[q]
                res.update(place_id=c["place_id"], qid=q, place_name=c["place_name"], match="name->candidate",
                           cand_admin_level=c["admin_level"],
                           issuing_body_code={"bonaire": "BQ-BO", "saba": "BQ-SA", "sinteustatius": "BQ-SE"}.get(n))
            self.cache[key] = res
            return res
        if sl == "waterschap":
            wn = wnorm(name)
            r = self.add_by_name.get(("water_board", WS_SUCC.get(wn, wn)))
            if r:
                self._from_addition(res, r, "waterboard_name->additions(nl_tooi)" if wn not in WS_SUCC
                                    else "former_waterboard->successor->additions(nl_tooi)")
                if wn in WS_SUCC:
                    res["successor_qid"] = res["qid"]
            self.cache[key] = res
            return res
        if scheme == "Provincie":
            iso = PROV_ISO.get(name) or next((v for k, v in PROV_ISO.items() if norm(k) == n), None)
            if iso:
                q = next((qq for qq, r in self.cand.items() if r["iso_3166_2"] == iso and r["admin_level"] == "adm1"), None)
                res.update(place_id=f"iso:{iso}", iso_3166_2=iso, qid=q, issuing_body_code=iso, match="province_iso",
                           place_name=self.cand[q]["place_name"] if q else name)
        elif scheme == "Gemeente":
            qs = {self.overrides[n]} if n in self.overrides else (self.current.get(n) or set())
            in_cand = [q for q in qs if q in self.cand]
            q = in_cand[0] if len(in_cand) == 1 else (next(iter(qs)) if len(qs) == 1 else None)
            if not q and in_cand:
                # ambiguous: prefer one with a CBS code
                q = next((x for x in in_cand if self.wd.get(x, {}).get("cbs")), None)
            if not q and self.former.get(n):
                q = sorted(self.former[n])[0]
                res["match"] = "former_municipality"
            if not q and self.manual_succ.get(n):
                c = self.cand[self.manual_succ[n]]
                res.update(place_id=c["place_id"], place_name=c["place_name"], iso_3166_2=c["iso_3166_2"] or None,
                           match="former_municipality->successor(manual)", successor_qid=self.manual_succ[n])
            if q:
                cbs = self.wd.get(q, {}).get("cbs")
                res["qid"] = q
                res["issuing_body_code"] = f"GM{cbs}" if cbs else None
                xp = XWALK.get("NL", cbs) if cbs else None   # shared crosswalk preferred
                if xp and xp[3:] in self.cand:
                    c = self.cand[xp[3:]]
                    res.update(place_id=c["place_id"], place_name=c["place_name"], iso_3166_2=c["iso_3166_2"] or None,
                               match=("cbs->crosswalk" if xp[3:] == q else "cbs->crosswalk(successor)"),
                               successor_qid=None if xp[3:] == q else xp[3:])
                    self.cache[key] = res
                    if res["place_id"].startswith("wd:"):
                        res["cand_admin_level"] = c.get("admin_level")
                    return res
                if xp and xp[3:] not in self.cand and ADDITIONS.row(xp):
                    self._from_addition(res, ADDITIONS.row(xp), "cbs->crosswalk->additions")
                    res["qid"] = q
                    self.cache[key] = res
                    return res
                succ = None
                if q not in self.cand:
                    succ = self.manual_succ.get(n) or self.successor.get(q)
                if succ:
                    c = self.cand[succ]
                    res.update(place_id=c["place_id"], place_name=c["place_name"], iso_3166_2=c["iso_3166_2"] or None,
                               match="former_municipality->successor", successor_qid=succ)
                elif q in self.cand:
                    c = self.cand[q]
                    res.update(place_id=c["place_id"], place_name=c["place_name"],
                               iso_3166_2=c["iso_3166_2"] or None, match=res["match"] or "name->wikidata->candidate")
                elif self.add_by_name.get(("municipality", n)):
                    self._from_addition(res, self.add_by_name[("municipality", n)], "name->additions")
                    res["qid"] = q
                else:
                    res["match"] = (res["match"] or "wikidata") + "_not_in_candidate"
        if res["place_id"] and res["place_id"].startswith("wd:"):
            res["cand_admin_level"] = self.cand.get(res["place_id"][3:], {}).get("admin_level")
        self.cache[key] = res
        return res


# ----------------------------------------------------------------------------- fetch
def first(v):
    return v[0] if isinstance(v, list) else v


def isodate(v) -> Optional[str]:
    v = first(v)
    if v and re.match(r"^\d{4}(-\d{2}(-\d{2})?)?$", v):
        return v
    return None


def build(meta: dict, xml: bytes, pm: PlaceMap, raw_path: Path, valid_on: str) -> dict:
    ident = meta["identifier"]
    work, ver = ident.rsplit("_", 1)
    root = ET.fromstring(xml)
    body = next((e for e in root.iter() if localtag(e.tag) == "body"), root)
    text = text_of(body)
    pl = pm.resolve(meta.get("creator", ""), meta.get("creator_scheme", ""))
    rec = {
        "place_id": pl["place_id"], "country_code": pl["country_code"], "doc_id": ident,
        "source_platform": "nl_cvdr",
        "source_url": meta.get("preferred_url") or f"https://lokaleregelgeving.overheid.nl/{work}/{ver}",
        "doc_type": "regulation", "language": first(meta.get("language")) or "nl",
        "title_native": first(meta.get("title")), "number": work,
        "adopted_date": isodate(meta.get("issued")), "published_date": None,
        "effective_date": isodate(meta.get("inwerkingtredingDatum")),
        "in_force": True, "consolidated": True, "content_format": "xml", "text": text,
        "retrieved_at": utcnow(),
        # place-level (SCHEMA.md optional)
        "place_name": pl["place_name"] or meta.get("creator"),
        "qid": (pl["place_id"][3:] if (pl["place_id"] or "").startswith("wd:") else pl["qid"]), "iso_3166_2": pl["iso_3166_2"],
        "admin_level": pl.get("cand_admin_level") or pl["level"], "platform": "nl_cvdr", "platform_place_id": pl["issuing_body_code"],
        # extra rich CVDR metadata (kept for later mapping / auditing)
        "cvdr_work_id": work, "cvdr_version": ver,
        "issuing_body_name": meta.get("creator"), "issuing_body_scheme": meta.get("creator_scheme"),
        "issuing_body_code": pl["issuing_body_code"], "issuing_body_qid": pl["qid"], "level": pl["level"],
        "place_match": pl["match"],
        "withdrawn_date": isodate(meta.get("uitwerkingtredingDatum")),
        "valid_on_query_date": valid_on, "cvdr_type": first(meta.get("type")),
        "ratified_by": meta.get("isRatifiedBy"), "subject": meta.get("subject"),
        "gazette_ref": meta.get("isFormatOf"), "legal_basis": meta.get("source"),
        "betreft": meta.get("betreft"), "kenmerk": meta.get("kenmerk"), "onderwerp": meta.get("onderwerp"),
        "modified": meta.get("modified"), "omgevingswet": meta.get("omgevingswet"),
        "work_url": meta.get("preferred_work_url"), "raw_xml_url": meta.get("publicatieurl_xml"),
        "raw_xml_path": str(raw_path), "sru_meta": meta, "rights": "CC0 / free of copyright & database right (KOOP)",
    }
    return rec


def atomic_write(path: Path, rows: list[dict], validate_pk: Optional[str] = None) -> None:
    """Write to a temp file (dot-prefixed '.<name>.tmp.jsonl': ignored by the uploader, but has a .jsonl
    suffix so schema.validate_file can read it), fsync, validate, then os.rename to the final name."""
    tmp = path.with_name("." + path.name[:-len(".jsonl")] + ".tmp.jsonl") if path.suffix == ".jsonl" \
        else path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    if validate_pk:
        v = get_schema().validate_file(tmp, expect_place_key=validate_pk)
        if not v["ok"]:
            raise RuntimeError(f"validate_file failed for {path.name}: {v['errors'][:3]} {v['file_errors']}")
    os.rename(tmp, path)


def flush_batch(bno: int, rows: list[dict], done_f) -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tag = f"cvdr_{ts}p0001"   # uploader: newer UTC timestamp wins per doc_id (bno kept only in the log)
    by_place: dict[str, list] = defaultdict(list)
    unmatched = []
    for r in rows:
        (by_place[r["place_id"]] if r["place_id"] else unmatched).append(r)
    stats = Counter()
    for pid, rs in by_place.items():
        d = OUT / rs[0]["country_code"]
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{schema_place_key(pid)}.{tag}.jsonl"
        sch = get_schema()
        if sch:
            bad = {r["doc_id"]: e for r in rs for e in [sch.validate_record(r)] if e}
            if bad:
                log.warning("%s: %d invalid rows -> _invalid/ e.g. %s", p.name, len(bad), list(bad.items())[:2])
                inv = OUT / "_invalid"
                inv.mkdir(exist_ok=True)
                atomic_write(inv / p.name, [dict(r, _errors=bad[r["doc_id"]]) for r in rs if r["doc_id"] in bad])
                rs = [r for r in rs if r["doc_id"] not in bad]
                if not rs:
                    continue
        atomic_write(p, rs, validate_pk=schema_place_key(pid) if sch else None)
        stats["matched"] += len(rs)
    if unmatched:
        atomic_write(UNM_DIR / f"cvdr_unmatched_{ts}p0001.jsonl", unmatched)
        stats["unmatched"] += len(unmatched)
    for r in rows:
        done_f.write(r["doc_id"] + "\n")
    done_f.flush()
    os.fsync(done_f.fileno())
    return stats


def build_queue(cat: Path, valid_on: str) -> Path:
    qp, mp = STATE / f"queue_{valid_on}.jsonl", STATE / f"queue_{valid_on}.meta.json"
    if qp.exists() and mp.exists() and json.loads(mp.read_text()).get("cat_size") == cat.stat().st_size:
        return qp
    keys, off = [], 0
    with cat.open("rb") as f:
        for raw in f:
            m = json.loads(raw)
            keys.append((m.get("creator_scheme", ""), m.get("creator", ""), m["identifier"], off))
            off += len(raw)
    keys.sort()
    tmp = qp.with_suffix(".tmp")
    with cat.open("rb") as f, tmp.open("wb") as o:
        for *_, off in keys:
            f.seek(off)
            o.write(f.readline())
    os.rename(tmp, qp)
    mp.write_text(json.dumps({"cat_size": cat.stat().st_size, "n": len(keys)}))
    del keys
    gc.collect()
    return qp


STOP = [False]


def _on_term(sig, _frm):   # graceful stop: finish the current doc, flush the buffer, exit
    STOP[0] = True


def fetch(valid_on: str, limit: Optional[int] = None) -> None:
    import signal
    signal.signal(signal.SIGTERM, _on_term)
    VALID_TAG[0] = valid_on.replace("-", "")
    cat = STATE / f"catalog_{valid_on}.jsonl"
    # group by issuing body so each batch touches few places; the sorted queue lives on disk (low memory)
    qp = build_queue(cat, valid_on)
    done_path = STATE / f"done_{valid_on}.txt"
    done = set(done_path.read_text().split()) if done_path.exists() else set()
    failed_path = STATE / f"failed_{valid_on}.jsonl"
    bstate = STATE / f"batchno_{valid_on}.txt"
    bno = int(bstate.read_text()) if bstate.exists() else 0
    n_all = sum(1 for _ in qp.open(encoding="utf-8"))
    n_todo = n_all - len(done)
    log.info("fetch: catalog=%d done=%d todo=%d next_batch=%d", n_all, len(done), n_todo, bno + 1)
    if limit:
        n_todo = min(n_todo, limit)

    def _todo():
        k = 0
        with qp.open(encoding="utf-8") as f:
            for ln in f:
                m = json.loads(ln)
                if m["identifier"] in done:
                    continue
                k += 1
                if limit and k > limit:
                    return
                yield m
    todo = _todo()
    pm = PlaceMap()
    rows: list[dict] = []
    rbytes = 0
    tot = Counter()
    t0 = time.time()
    with done_path.open("a", encoding="utf-8") as done_f, failed_path.open("a", encoding="utf-8") as fail_f:
        for i, m in enumerate(todo, 1):
            if STOP[0]:
                log.info("SIGTERM: flushing %d buffered docs and stopping (resume with `cvdr.py fetch`)", len(rows))
                break
            ident = m["identifier"]
            work, ver = ident.rsplit("_", 1)
            url = m.get("publicatieurl_xml") or f"{REPO}/{work}/{ver}/xml/{ident}.xml"
            raw = RAW_DIR / work / f"{ident}.xml.gz"
            try:
                if raw.exists():
                    xml = gzip.decompress(raw.read_bytes())
                elif not robots_ok(url):
                    raise PermissionError(f"robots.txt disallows {url}")
                else:
                    xml = http_get(url).content
                    raw.parent.mkdir(parents=True, exist_ok=True)
                    raw.write_bytes(gzip.compress(xml))
                rows.append(build(m, xml, pm, raw, valid_on))
                rbytes += len(rows[-1].get("text") or "") + len(rows[-1].get("html") or "")
                del xml
            except Exception as e:  # noqa: BLE001
                log.warning("FAIL %s %s: %s", ident, url, e)
                fail_f.write(json.dumps({"identifier": ident, "url": url, "error": str(e)[:500], "at": utcnow()}) + "\n")
                fail_f.flush()
            if len(rows) >= BATCH_DOCS or rbytes >= 16 * 1024 * 1024 or (i == n_todo and rows):
                bno += 1
                s = flush_batch(bno, rows, done_f)
                bstate.write_text(str(bno))
                tot.update(s)
                rows, rbytes = [], 0
                gc.collect()
                rate = i / max(time.time() - t0, 1)
                log.info("batch %04d written matched=%d unmatched=%d | progress %d/%d (%.2f doc/s, ETA %.1fh)",
                         bno, s["matched"], s["unmatched"], i, n_todo, rate, (n_todo - i) / rate / 3600)
    if rows:
        bno += 1
        tot.update(flush_batch(bno, rows, done_f2 := done_path.open("a", encoding="utf-8")))
        done_f2.close()
        bstate.write_text(str(bno))
    log.info("fetch finished: %s", dict(tot))


def status(valid_on: str) -> None:
    st = STATE / f"discover_{valid_on}.json"
    print("discover:", st.read_text() if st.exists() else None)
    dp = STATE / f"done_{valid_on}.txt"
    print("done docs:", len(dp.read_text().split()) if dp.exists() else 0)
    places, unm, ndocs = Counter(), Counter(), 0
    for p in OUT.glob("[A-Z][A-Z]/*.cvdr*_b*.jsonl"):
        for l in p.open(encoding="utf-8"):
            r = json.loads(l)
            places[r["place_id"]] += 1
    for p in UNM_DIR.glob("cvdr_unmatched_*.jsonl"):
        for l in p.open(encoding="utf-8"):
            r = json.loads(l)
            unm[(r["issuing_body_scheme"], r["issuing_body_name"])] += 1
    print(f"matched docs={sum(places.values())} distinct places={len(places)}")
    print(f"unmatched docs={sum(unm.values())} distinct bodies={len(unm)}")
    print("by level (unmatched):", Counter(k[0] for k in unm))
    for k, v in unm.most_common(15):
        print("  ", v, k)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["discover", "fetch", "all", "status"])
    ap.add_argument("--valid-on", default=os.environ.get("CVDR_VALID_ON", "2026-10-10"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--test", type=int, help="fetch N random catalog docs into staging/eu/_test/")
    a = ap.parse_args()
    setup_logging()
    if a.test:
        global OUT, NL_DIR, UNM_DIR, STATE
        import random
        OUT = OUT / "_test"; NL_DIR = OUT / "NL"; UNM_DIR = OUT / "_unmatched"; STATE = OUT / "_state"
        for d in (NL_DIR, UNM_DIR, STATE):
            d.mkdir(parents=True, exist_ok=True)
        src = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu/_state")) / f"catalog_{a.valid_on}.jsonl"
        lines = src.read_text(encoding="utf-8").splitlines()
        random.seed(7)
        (STATE / f"catalog_{a.valid_on}.jsonl").write_text("\n".join(random.sample(lines, a.test)) + "\n", encoding="utf-8")
        return fetch(a.valid_on)
    if a.cmd == "status":
        return status(a.valid_on)
    log.info("start %s valid_on=%s pid=%d", a.cmd, a.valid_on, os.getpid())
    if a.cmd in ("discover", "all"):
        discover(a.valid_on)
    if a.cmd in ("fetch", "all"):
        fetch(a.valid_on, a.limit)


if __name__ == "__main__":
    main()
