#!/usr/bin/env python3
"""Build the shared place-code crosswalk: place_id (wd:Q… / gnis:N / KG-kg_cbd:<organ id>) -> national statistical/admin codes.

Outputs (next to this file):
  place_codes.parquet / place_codes.csv        long format, one row per (place_id, code_system, code)
  place_codes_wide.parquet / place_codes_wide.csv  one row per place_id, one column per code_system (current codes, ';'-joined)
  coverage.json                                coverage/conflict summary used by README.md
  conflicts.csv                                Wikidata codes not in the official list, or name disagreements

Sources, in priority order:
  1. Wikidata statements, fetched in bulk (one query per property) from the QLever Wikidata endpoint
     (https://qlever.dev/api/wikidata; an index of the dumps.wikimedia.org entity dump, live-updated).
     query.wikidata.org is NOT used.  Cached as cache/wd_<P>.tsv (use --refresh to re-fetch).
  2. Official national code lists in cache/ (Eurostat LAU 2024, INSEE COG 2025, ISTAT, INE 2025, Statistik Austria,
     soumu.go.jp, IBGE API, INEI UBIGEO 2022, Statistics Canada 2021 CSD list) for cross-checking and for filling gaps by unique name match.
  3. Our own place list: /workspace/global_municipalities/global_municipalities_candidate.csv, plus
     codes/place_additions.csv (places missing from the candidate list: PL powiats, NL water boards, 5 Frisian
     municipalities, CA census subdivisions, PL gminas, GR former municipalities; built by build_place_additions.py), plus place keys seen in /workspace/world_law/staging (read-only).
  4. Reviewed proposals in codes/proposed/: PL_powiaty.csv (4-digit powiat TERC), PL_gmina_fill_reviewed.csv (7-digit
     gmina TERC, decision=accept), GR_diavgeia_orgs.csv (gr_diavgeia_org = Diavgeia organisation uid),
     GB_gss_reviewed.csv (gb_gss = ONS GSS code, decision=accept; checked against the ONS Code History Database).

Run: PYTHONPATH=/path/with/openpyxl /workspace/hf-venv/bin/python build_place_codes.py [--refresh]
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import argparse
import collections
import csv
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
CANDIDATE = Path(os.environ.get("GLOBAL_MUNICIPALITIES_CSV", "/workspace/global_municipalities/global_municipalities_candidate.csv"))
ADDITIONS = Path(os.environ.get("PLACE_ADDITIONS_CSV", str(HERE / "place_additions.csv")))
KG_BODIES = Path(os.environ.get("KG_BODY_TO_PLACE_CSV", "/workspace/world_law/codes_ext/kg_body_to_place.csv"))
STAGING = Path(os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law")) / "staging"
QLEVER = "https://qlever.dev/api/wikidata"
UA = "world-law-place-codes/0.1 (Benjamin Barber; low volume; bulk via QLever)"

# code_system, country (None = any), Wikidata property, normaliser, validation regex
SYSTEMS = [
    ("nl_cbs_gemeente", "NL", "P382", lambda v: v.zfill(4) if v.isdigit() else v, r"\d{4}"),
    ("pl_teryt_terc", "PL", "P1653", str, r"\d{2}|\d{4}|\d{7}|\d{10}"),  # 10 digits = NTS-style value (split below)
    ("cz_ruian_obec", "CZ", "P7606", str, r"\d{6}"),          # obec code = ZÚJ code for municipalities
    ("hu_ksh", "HU", "P939", lambda v: v.zfill(5) if v.isdigit() else v, r"\d{5}"),
    ("at_gkz", "AT", "P964", str, r"\d{5}"),
    ("es_ine", "ES", "P772", str, r"\d{5}|\d{11}"),          # 5 = municipio, 11 = entidad/núcleo de población
    ("it_istat", "IT", "P635", lambda v: v.zfill(6) if v.isdigit() and len(v) >= 4 else v, r"\d{2}|\d{3}|\d{6}"),
    ("fr_insee_cog", "FR", "P374", str, r"[0-9][0-9AB]\d{3}"),
    ("de_ags", "DE", "P439", str, r"\d{2}|\d{3}|\d{5}|\d{8}"),
    ("ch_bfs", "CH", "P771", str, r"\d{1,4}"),
    ("jp_dantai", "JP", "P429", lambda v: v.zfill(6) if v.isdigit() else v, r"\d{6}"),
    ("br_ibge", "BR", "P1585", str, r"\d{7}"),
    ("mx_inegi", "MX", "P3801", lambda v: v.zfill(5) if v.isdigit() else v, r"\d{5}"),
    ("pe_ubigeo", "PE", "P844", lambda v: v.zfill(len(v) + len(v) % 2) if v.isdigit() else v, r"\d{2}|\d{4}|\d{6}"),
    ("cl_cut", "CL", "P6929", lambda v: v.zfill(5) if v.isdigit() and len(v) == 4 else v, r"\d{2}|\d{3}|\d{5}"),
    ("id_bps", "ID", "P1588", str, r"\d{2}|\d{4}|\d{7}|\d{10}"),
    ("id_kemendagri", "ID", "P2588", str, r"\d{2}(\.\d{2}){0,3}(\.\d{4})?"),
    ("nl_tooi", "NL", "P11767", lambda v: v.rsplit("/", 1)[-1].lower(), r"[a-z]{2,4}\d{2,8}"),  # TOOI organisatiecode
    ("ca_sgc_csd", "CA", "P3012", str, r"\d{2}|\d{4}|\d{6}|\d{7}"),  # 7 = CSDUID; 2/4 = province/CD
    ("ph_psgc", "PH", "P988", lambda v: ph_psgc10(v), r"\d{10}"),  # PSA 10-digit (2023+); 9-digit WD values converted
    ("eu_lau", None, "P782", str, r".+"),
    ("eu_nuts", None, "P605", str, r"[A-Z]{2}[0-9A-Z]{0,3}"),
]
# PH: 9-digit PSGC (pre-2023) -> 10-digit. Default inserts '0' before the 2-digit province (RR PP MM BBB ->
# RR 0PP MM BBB). Exceptions (HUCs renumbered as 'province-level' 10-digit codes, Negros Island Region 18 created
# 2024, Cotabato City moved to BARMM) come from cache/ph_cities.jsonl (codes_ext/build_ph_cities.py, matched by
# name to the PSA PSGC 1Q 2026 publication datafile); NIR provinces 0645/0746/0761 -> 18 0PP.
_PH_XWALK = None


def ph_psgc10(v: str) -> str:
    global _PH_XWALK
    v = (v or "").strip()
    if _PH_XWALK is None:
        _PH_XWALK = {}
        p = CACHE / "ph_cities.jsonl"
        if p.exists():
            for line in p.open(encoding="utf-8"):
                c = json.loads(line)
                for w in (c.get("psgc_code_wikidata") or "").split("; "):
                    if w and w != c["psgc_code"]:
                        _PH_XWALK[w] = c["psgc_code"]
    if v in _PH_XWALK:
        return _PH_XWALK[v]
    if re.fullmatch(r"\d{9}", v):
        v = v[:2] + "0" + v[2:]
    if re.fullmatch(r"\d{10}", v):   # stale regional prefixes: NIR (2024), ARMM 15 -> BARMM 19, Sulu -> Region IX (2024)
        if v[:5] in ("06045", "07046", "07061"):
            return "18" + v[2:]
        if v[:2] == "15":
            v = "19" + v[2:]
        if v[:5] == "19066":
            return "09" + v[2:]
    return v


EU_LAU_COUNTRIES = ["NL", "PL", "CZ", "HU", "AT", "ES", "IT", "FR", "DE", "CH"]


def now_iso(ts=None):
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_name(s: str) -> str:
    m = re.match(r"^(.*?),\s*(la|las|el|los|l'|a|as|o|os|es|sa|ses|s'|lo|le|les|il|der|die|das)\s*$", str(s or ""), re.I)
    if m:  # INE/ISTAT style "Herrera, La" -> "La Herrera"
        s = f"{m.group(2)} {m.group(1)}"
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\bst\.?\s", "sankt ", s) if re.search(r"\b(sankt|st\.)", s) else s
    s = re.sub(r"\b(municipality|municipio|municipalite|gemeinde|comune di|commune|district|distrito|"
               r"landeshauptstadt|stadt|hansestadt|universitatsstadt|markt|city|town|gmina|miasto|obec|mesto|"
               r"provincia de|province)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def qlever(query: str, out: Path, refresh: bool) -> Path:
    if out.exists() and out.stat().st_size > 50 and not refresh:
        return out
    tmp = out.with_suffix(".tmp")
    subprocess.run(["curl", "-sS", "-m", "900", "--retry", "3", "--retry-delay", "20", "-A", UA,
                    "-H", "Accept: text/tab-separated-values", "--data-urlencode", f"query={query}", QLEVER,
                    "-o", str(tmp)], check=True)
    tmp.replace(out)
    time.sleep(1)
    return out


PREFIX = ("PREFIX p: <http://www.wikidata.org/prop/> PREFIX ps: <http://www.wikidata.org/prop/statement/> "
          "PREFIX pq: <http://www.wikidata.org/prop/qualifier/> PREFIX wikibase: <http://wikiba.se/ontology#> "
          "PREFIX wdt: <http://www.wikidata.org/prop/direct/> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
          "PREFIX wd: <http://www.wikidata.org/entity/> ")


def fetch_prop(P: str, refresh: bool) -> Path:
    q = (PREFIX + f"SELECT ?item ?v ?rank (SAMPLE(?e) AS ?end) (SAMPLE(?s) AS ?start) (SAMPLE(?t) AS ?pit) WHERE {{ "
         f"?item p:{P} ?st . ?st ps:{P} ?v . ?st wikibase:rank ?rank . OPTIONAL {{ ?st pq:P582 ?e }} "
         f"OPTIONAL {{ ?st pq:P580 ?s }} OPTIONAL {{ ?st pq:P585 ?t }} }} GROUP BY ?item ?v ?rank")
    return qlever(q, CACHE / f"wd_{P}.tsv", refresh)


def read_tsv(path: Path):
    uq = lambda s: s.strip().strip("<>").rsplit("/", 1)[-1] if s.startswith("<") else re.sub(r'^"|"(\^\^.*|@[a-z\-]+)?$', "", s.strip())
    with path.open(encoding="utf-8") as f:
        next(f)
        for line in f:
            p = line.rstrip("\n").split("\t")
            yield [uq(x) for x in p]


# ---------------------------------------------------------------------------
# official lists -> {code_system: {code: name}}
# ---------------------------------------------------------------------------
def load_official():
    off, meta = {}, {}

    def lau(cc):
        rows = list(csv.DictReader((CACHE / f"eurostat_lau_2024_{cc}.csv").open(encoding="utf-8")))
        return [r for r in rows if r.get("LAU CODE")]
    try:
        import openpyxl  # noqa: F401
        have_xlsx = True
    except ImportError:
        have_xlsx = False
        print("WARN openpyxl not importable: soumu/INE/INEI xlsx skipped", file=sys.stderr)

    lau_rows = {cc: lau(cc) for cc in EU_LAU_COUNTRIES if (CACHE / f"eurostat_lau_2024_{cc}.csv").exists()}
    meta["eurostat_lau_2024"] = "https://ec.europa.eu/eurostat/documents/345175/501971/EU-27-LAU-2024-NUTS-2024.xlsx"
    # national code -> LAU row
    lau_by_nat = {}
    for cc, rows in lau_rows.items():
        for r in rows:
            code = str(r["LAU CODE"]).strip()
            nat = {"NL": code[2:] if code.startswith("GM") else None,
                   "CH": code[2:].lstrip("0") if code.startswith("CH") else None,
                   "PL": None}.get(cc, code)
            if cc in ("AT",) and nat:
                nat = nat.zfill(5)
            if cc == "CZ" and nat:
                nat = nat.zfill(6)
            if nat:
                lau_by_nat[(cc, nat)] = r
    sysmap = {"NL": "nl_cbs_gemeente", "CZ": "cz_ruian_obec", "HU": "hu_ksh", "AT": "at_gkz", "ES": "es_ine",
              "IT": "it_istat", "FR": "fr_insee_cog", "DE": "de_ags", "CH": "ch_bfs"}
    for (cc, nat), r in lau_by_nat.items():
        off.setdefault(sysmap[cc], {})[nat] = (r["LAU NAME NATIONAL"], "eurostat_lau_2024")
    off["eu_lau"] = {f'{cc}_{str(r["LAU CODE"]).strip()}': (r["LAU NAME NATIONAL"], "eurostat_lau_2024")
                     for cc, rows in lau_rows.items() for r in rows}
    off["_lau_names"] = {cc: [(str(r["LAU CODE"]).strip(), r["LAU NAME NATIONAL"], r["NUTS3"]) for r in rows]
                         for cc, rows in lau_rows.items()}
    nuts3 = {r["NUTS3"] for rows in lau_rows.values() for r in rows if r.get("NUTS3")}
    off["_nuts3"] = nuts3
    # more current national lists override the LAU-derived name for the same code
    p = CACHE / "statat_gemliste_knz.csv"
    if p.exists():
        raw = p.read_bytes()
        try:
            lines = raw.decode("utf-8-sig").splitlines()
        except UnicodeDecodeError:
            lines = raw.decode("latin-1").splitlines()
        for row in csv.reader(lines[3:], delimiter=";"):
            if row and row[0].isdigit():
                off.setdefault("at_gkz", {})[row[0].zfill(5)] = (row[1], "statistik_austria_gemliste_2026")
        meta["statistik_austria_gemliste_2026"] = "https://www.statistik.at/verzeichnis/reglisten/gemliste_knz.csv"
    p = CACHE / "istat_comuni.csv"
    if p.exists():
        rows = list(csv.reader(p.read_bytes().decode("latin-1").splitlines(), delimiter=";"))
        hdr = rows[0]
        ci = [i for i, h in enumerate(hdr) if "alfanumerico" in h][0]
        ni = [i for i, h in enumerate(hdr) if h.strip() == "Denominazione in italiano"][0]
        for r in rows[1:]:
            if len(r) > ni and r[ci].strip():
                off.setdefault("it_istat", {})[r[ci].strip().zfill(6)] = (r[ni], "istat_elenco_comuni")
        meta["istat_elenco_comuni"] = "https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.csv"
    p = CACHE / "insee_cog_2025.zip"
    if p.exists():
        with zipfile.ZipFile(p) as z:
            with z.open("v_commune_2025.csv") as f:
                for r in csv.DictReader(line.decode("utf-8-sig") for line in f):
                    if r["TYPECOM"] in ("COM", "ARM"):
                        off.setdefault("fr_insee_cog", {})[r["COM"]] = (r["LIBELLE"], "insee_cog_2025")
        meta["insee_cog_2025"] = "https://www.insee.fr/fr/statistiques/fichier/8377162/cog_ensemble_2025_csv.zip"
    p = CACHE / "ibge_municipios.json"
    if p.exists():
        for m in json.loads(p.read_text()):
            off.setdefault("br_ibge", {})[str(m["id"])] = (m["nome"], "ibge_api_localidades")
        meta["ibge_api_localidades"] = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
    if have_xlsx:
        import openpyxl
        p = CACHE / "soumu_codes.xlsx"
        if p.exists():
            wb = openpyxl.load_workbook(p, read_only=True)
            for sn in wb.sheetnames:
                for i, r in enumerate(wb[sn].iter_rows(values_only=True)):
                    if i and r[0] and str(r[0]).isdigit():
                        off.setdefault("jp_dantai", {})[str(r[0]).zfill(6)] = ((r[2] or r[1]), "soumu_dantai_code_r6")
            meta["soumu_dantai_code_r6"] = "https://www.soumu.go.jp/main_content/000925835.xlsx"
        p = CACHE / "ine_es_diccionario25.xlsx"
        if p.exists():
            wb = openpyxl.load_workbook(p, read_only=True)
            for i, r in enumerate(wb.worksheets[0].iter_rows(values_only=True)):
                if i > 1 and r[1] and r[2]:
                    off.setdefault("es_ine", {})[f"{str(r[1]).zfill(2)}{str(r[2]).zfill(3)}"] = (r[4], "ine_diccionario_2025")
            meta["ine_diccionario_2025"] = "https://www.ine.es/daco/daco42/codmun/diccionario25.xlsx"
        p = CACHE / "inei_ubigeo_2022.xlsx"
        if p.exists():
            wb = openpyxl.load_workbook(p, read_only=True)
            pe = {}
            for i, r in enumerate(wb.worksheets[0].iter_rows(values_only=True)):
                if i and r[0]:
                    pe[str(r[0]).zfill(6)] = (r[3], "inei_ubigeo_2022", r[1], r[2])
            off["pe_ubigeo"] = {k: v[:2] for k, v in pe.items()}
            off["_pe_full"] = pe
            meta["inei_ubigeo_2022"] = "https://www.datosabiertos.gob.pe/sites/default/files/UBIGEO%202022_1891%20distritos.xlsx"
    p = CACHE / "statcan_csd_2021.csv"   # written by build_place_additions.py from statcan_98100002_csd_2021.zip
    if p.exists():
        with p.open(encoding="utf-8") as f:
            _ca = list(csv.DictReader(f))
            off["ca_sgc_csd"] = {r["csduid"]: (r["name"], "statcan_98100002_csd_2021") for r in _ca}
            off["_ca_csd_full"] = _ca
        meta["statcan_98100002_csd_2021"] = ("https://www150.statcan.gc.ca/n1/tbl/csv/98100002-eng.zip "
                                             "(table 98-10-0002-01, 2021 Census subdivisions, CSDUID + CSD type)")
    p = CACHE / "psa_psgc_1q2026_cities_municipalities.json"
    if p.exists():   # PSA PSGC 1Q 2026 publication datafile (parsed by github.com/alkevintan/psgc-rb; PSA site is CF-gated)
        ph = {}
        for fn in ("psa_psgc_1q2026_regions.json", "psa_psgc_1q2026_provinces.json",
                   "psa_psgc_1q2026_cities_municipalities.json"):
            for o in json.loads((CACHE / fn).read_text()):
                ph[o["code"]] = (o["name"], "psa_psgc_1q2026")
        off["ph_psgc"] = ph
        meta["psa_psgc_1q2026"] = ("https://psa.gov.ph/classification/psgc (PSGC 1Q 2026 Publication Datafile, as parsed "
                                   "into JSON by github.com/alkevintan/psgc-rb data/*.json; regions, provinces, cities, "
                                   "municipalities, sub-municipalities)")
    p = CACHE / "gus_bdl_powiaty.json"
    if p.exists():   # GUS BDL level-5 units = powiats (incl. cities with powiat rights); TERYT = id[2:4] + id[7:9]
        off["pl_teryt_terc"] = {o["teryt"]: (re.sub(r"(?i)^powiat (m\. (st\. )?)?", "", o["name"]), "gus_bdl_units_level5")
                                for o in json.loads(p.read_text()) if "do 20" not in o["name"]}
        meta["gus_bdl_units_level5"] = "https://bdl.stat.gov.pl/api/v1/units?level=5 (powiats only; 7-digit TERC unchecked)"
    p = CACHE / "tooi_rwc_waterschappen_compleet_2.json"
    if p.exists():   # TOOI waardelijst waterschappen (current = no einddatum)
        T = "https://identifier.overheid.nl/tooi/def/ont/"
        ws, wsc = {}, {}
        for x in json.loads(p.read_text()):
            if "HistorischeVersie" in str(x.get("@type")):
                continue
            g = lambda k: (x.get(T + k) or [{}])[0].get("@value")
            if g("organisatiecode") and str(g("organisatiecode")).startswith("ws") and not g("einddatum"):
                ws[g("organisatiecode")] = (g("officieleNaamInclSoort"), "tooi_rwc_waterschappen_compleet_2")
                wsc[g("organisatiecode")] = g("waterschapscode")
        off["nl_tooi"], off["_nl_waterschapscode"] = ws, wsc
        meta["tooi_rwc_waterschappen_compleet_2"] = ("https://repository.officiele-overheidspublicaties.nl/waardelijsten/"
                                                     "rwc_waterschappen_compleet/2/json/rwc_waterschappen_compleet_2.json")
    return off, meta, lau_by_nat


# CA: SGC level by code length for P3012 values that are not 7-digit CSDUIDs
CA_SGC_LEVEL = {2: "ca_sgc_pr", 4: "ca_sgc_cd", 6: "ca_sgc_dpl"}
CA_SINGLE_TIER_TYPES = {"C", "CY", "V", "CV", "MU", "T", "TP", "RGM", "VL", "CT", "CU"}


def _ca_norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()
    s = re.sub(r"^(city|town|county|ville|cite) (of|de) ", "", s)
    s = re.sub(r" regional municipality$", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def ca_single_csd(p, code: str, csds) -> str:
    """7-digit CSDUID when the place is itself a single-tier municipality = exactly one CSD inside the census
    division `code` with the same name (qualifiers like County/Regional/District must match too, so
    'Peterborough County' never maps to the city of Peterborough) and a legislating municipal CSD type."""
    if len(code) != 4 or p.get("admin_level") not in ("municipality", ""):
        return ""
    nm = _ca_norm(p.get("name") or "")
    hits = [c["csduid"] for c in csds if c["csduid"].startswith(code) and c["csd_type"] in CA_SINGLE_TIER_TYPES
            and nm and _ca_norm(c["name"]) == nm]
    return hits[0] if len(hits) == 1 else ""


# ---------------------------------------------------------------------------
def load_places():
    places = {}
    with CANDIDATE.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pid = r["place_id"].strip()
            if not pid:
                continue
            places[pid] = {"place_id": pid, "country_code": r["country_code"], "qid": (r.get("qid") or "").strip(),
                           "name": r.get("place_name") or "", "admin_level": r.get("admin_level") or "",
                           "census_geoid": (r.get("census_geoid") or "").strip(), "from": "candidate"}
    n_add = 0
    if ADDITIONS.exists():
        with ADDITIONS.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                pid = r["place_id"].strip()
                if not pid or pid in places:
                    continue
                places[pid] = {"place_id": pid, "country_code": r["country_code"], "qid": (r.get("qid") or "").strip(),
                               "name": r.get("name") or "", "name_native": r.get("name_native") or "",
                               "admin_level": r.get("admin_level") or "", "census_geoid": "", "from": "additions",
                               "official_code_system": r.get("official_code_system") or "",
                               "official_code": r.get("official_code") or "", "add_source": r.get("source") or ""}
                n_add += 1
    places["_n_add"] = n_add
    n_stage = 0
    if STAGING.exists():
        for bot in STAGING.iterdir():
            if not bot.is_dir() or bot.name.startswith(("_", ".")):
                continue
            for cc in bot.iterdir():
                if not re.fullmatch(r"[A-Z]{2}", cc.name):
                    continue
                for fn in os.listdir(cc):
                    m = re.match(r"^wd_(Q\d+)\.", fn)
                    if m and f"wd:{m.group(1)}" not in places:
                        places[f"wd:{m.group(1)}"] = {"place_id": f"wd:{m.group(1)}", "country_code": cc.name,
                                                      "qid": m.group(1), "name": "", "admin_level": "",
                                                      "census_geoid": "", "from": "staging"}
                        n_stage += 1
    return places, n_stage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-fetch Wikidata property values from QLever")
    args = ap.parse_args()
    CACHE.mkdir(exist_ok=True)
    places, n_stage = load_places()
    n_add = places.pop("_n_add")
    by_qid = collections.defaultdict(list)
    for p in places.values():
        if p["qid"]:
            by_qid[p["qid"]].append(p)
    print(f"places: {len(places)} ({n_add} from place_additions.csv, {n_stage} only in staging), with qid: {len(by_qid)}")

    off, off_meta, lau_by_nat = load_official()
    rows = []          # long rows
    conflicts = []
    seen = set()

    def add(pid, cc, system, code, prop, source, ra, **extra):
        k = (pid, system, code)
        if k in seen:
            return
        seen.add(k)
        rows.append({"place_id": pid, "country_code": cc, "code_system": system, "code": code,
                     "wikidata_property": prop, "source": source, "retrieved_at": ra,
                     "is_current": extra.get("is_current", True), "wd_rank": extra.get("wd_rank"),
                     "valid_from": extra.get("valid_from"), "valid_to": extra.get("valid_to"),
                     "official_check": extra.get("official_check")})

    # 1) Wikidata
    for system, cc_sys, P, normf, rx in SYSTEMS:
        path = fetch_prop(P, args.refresh)
        ra = now_iso(path.stat().st_mtime)
        per_item = collections.defaultdict(list)
        for it in read_tsv(path):
            if len(it) < 3 or it[0] not in by_qid:
                continue
            q, v, rank = it[0], it[1].strip(), it[2]
            end, start, pit = (it + ["", "", ""])[3:6]
            if "Deprecated" in rank or not v:
                continue
            per_item[q].append((v, rank, end, start, pit))
        for q, vals in per_item.items():
            pref = [x for x in vals if "Preferred" in x[1]]
            use = pref or vals
            for p in by_qid[q]:
                cc = p["country_code"]
                if cc_sys and cc != cc_sys:
                    continue
                for v, rank, end, start, pit in use:
                    code = normf(v)
                    if not re.fullmatch(rx, code):
                        conflicts.append({"place_id": p["place_id"], "country_code": cc, "code_system": system,
                                          "code": code, "issue": "bad_format_on_wikidata", "official_name": "",
                                          "our_name": p["name"]})
                        continue
                    sys_out = system
                    if system == "pl_teryt_terc" and len(code) == 10:
                        sys_out = "pl_nts"   # GUS NTS code stored under P1653 on some items
                    if system == "ca_sgc_csd" and len(code) != 7:
                        # P3012 with a province (2) / census-division (4) / designated-place (6) code: a single-tier
                        # city that IS one CSD gets its real CSDUID; otherwise the code is kept under the matching
                        # SGC level (ca_sgc_cd for counties / regional districts / regional municipalities).
                        csd = ca_single_csd(p, code, off.get("_ca_csd_full") or [])
                        if csd:
                            add(p["place_id"], cc, "ca_sgc_csd", csd, P,
                                f"wikidata(qlever) P3012={code} -> statcan_98100002_csd_2021 name+CD match", ra,
                                is_current=not end, wd_rank=rank.rsplit("#", 1)[-1],
                                valid_from=start or pit or None, valid_to=end or None, official_check="match")
                        else:
                            add(p["place_id"], cc, CA_SGC_LEVEL[len(code)], code, P, "wikidata(qlever)", ra,
                                is_current=not end, wd_rank=rank.rsplit("#", 1)[-1], valid_from=start or pit or None,
                                valid_to=end or None, official_check=None)
                        continue
                    if (system == "it_istat" and len(code) != 6 or system == "pe_ubigeo" and len(code) != 6):
                        add(p["place_id"], cc, sys_out, code, P, "wikidata(qlever)", ra, is_current=not end,
                            wd_rank=rank.rsplit("#", 1)[-1], valid_from=start or pit or None, valid_to=end or None,
                            official_check="not_municipal_level")
                        continue
                    chk = None
                    o = off.get(system)
                    if system == "pl_teryt_terc" and len(code) != 4 or system == "nl_tooi" and not code.startswith("ws"):
                        o = None   # official list loaded only for powiats / water boards
                    if system == "eu_lau":
                        o = off.get("eu_lau")
                        code_l = code if "_" in code else (code[:2] + "_" + code[2:] if code[:2].isalpha() else code)
                        code = code_l
                    if system == "eu_nuts" and off.get("_nuts3"):
                        chk = "match" if any(n.startswith(code) for n in off["_nuts3"]) else (
                            "not_in_official_list" if cc in EU_LAU_COUNTRIES else None)
                    elif o is not None and (system != "eu_lau" or cc in EU_LAU_COUNTRIES):
                        hit = o.get(code)
                        if hit is None:
                            chk = "not_in_official_list"
                            if not end:
                                conflicts.append({"place_id": p["place_id"], "country_code": cc, "code_system": system,
                                                  "code": code, "issue": "wikidata_code_not_in_official_list",
                                                  "official_name": "", "our_name": p["name"]})
                        else:
                            a, b = norm_name(hit[0]), norm_name(p["name"])
                            bn = norm_name(re.sub(r"(?i)^(powiat|waterschap|hoogheemraadschap( van)?|wetterskip)\s+", "", p.get("name_native") or ""))
                            if bn and (a == bn or a in bn or bn in a or a.split()[:1] == bn.split()[:1]):
                                b = bn
                            if cc == "JP" or not b or a == b or a in b or b in a or a.split()[:1] == b.split()[:1]:
                                chk = "match"
                            else:
                                chk = "match_code_name_differs"
                                conflicts.append({"place_id": p["place_id"], "country_code": cc, "code_system": system,
                                                  "code": code, "issue": "name_differs", "official_name": hit[0],
                                                  "our_name": p["name"]})
                    add(p["place_id"], cc, sys_out, code, P, "wikidata(qlever)", ra, is_current=not end,
                        wd_rank=rank.rsplit("#", 1)[-1], valid_from=start or pit or None, valid_to=end or None,
                        official_check=chk)
        print(f"  {system:18s} {P:6s} items_in_our_list={len(per_item)}")

    have = collections.defaultdict(set)  # (place_id) -> systems
    used = collections.defaultdict(set)  # system -> codes already assigned (current)
    for r in rows:
        if r["is_current"]:
            have[r["place_id"]].add(r["code_system"])
            used[r["code_system"]].add(r["code"])

    # 2) derived: JIS X 0402 (5 digits) from dantai code
    for r in list(rows):
        if r["code_system"] == "jp_dantai" and r["is_current"]:
            add(r["place_id"], "JP", "jp_jis_x0402", r["code"][:5], "P429", "derived:jp_dantai[:5]", r["retrieved_at"],
                official_check=r["official_check"])

    # 2b) PL: 4-digit powiat TERYT for cities with powiat rights (miasto na prawach powiatu, powiat digits 61-99)
    #     derived from the city's 7-digit TERC when Wikidata has no 4-digit value; must be in GUS BDL
    bdl = off.get("pl_teryt_terc") or {}
    pl4 = {r["code"] for r in rows if r["code_system"] == "pl_teryt_terc" and len(r["code"]) == 4 and r["is_current"]}
    for r in list(rows):
        c = r["code"]
        if (r["code_system"] == "pl_teryt_terc" and r["is_current"] and len(c) == 7 and c[2:4] >= "61"
                and c[:4] in bdl and c[:4] not in pl4 and places.get(r["place_id"], {}).get("admin_level") == "municipality"):
            add(r["place_id"], "PL", "pl_teryt_terc", c[:4], "P1653",
                "derived:pl_teryt_terc[:4] (city with powiat rights); gus_bdl_units_level5", r["retrieved_at"],
                official_check="match")
            pl4.add(c[:4])
    # 2b2) reviewed proposals (2026-10-17, plgr). Runs before 2c so a former place's code keeps is_current=False.
    #   - codes/proposed/PL_powiaty.csv: 4-digit powiat TERC -> place (land powiat or city with powiat rights);
    #     rows without a place_id (historical 0263, 1431) are skipped. Checked against GUS BDL.
    #   - codes/proposed/PL_gmina_fill_reviewed.csv (decision=accept): 7-digit gmina TERC; checked against the TERC
    #     digits inside the Eurostat LAU 2024 PL code (LAU[4:6] + LAU[9:13] = woj+pow+gmi; type digit not in LAU).
    #     A Wikidata 7-digit value on the same place that is not in that list is flagged not_in_official_list.
    #   - codes/proposed/GR_diavgeia_orgs.csv: gr_diavgeia_org = Diavgeia (diavgeia.gov.gr) organisation uid.
    prop_dir = HERE / "proposed"
    lau_pl6 = set()
    p_lau = CACHE / "eurostat_lau_2024_PL.csv"
    if p_lau.exists():
        with p_lau.open(encoding="utf-8") as f:
            lau_pl6 = {r["LAU CODE"][4:6] + r["LAU CODE"][9:13] for r in csv.DictReader(f) if len(r["LAU CODE"]) == 13}
    fp = prop_dir / "PL_powiaty.csv"
    if fp.exists():
        with fp.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                pid, code = (r.get("place_id") or "").strip(), (r.get("teryt") or "").strip()
                if pid in places and re.fullmatch(r"\d{4}", code):
                    add(pid, "PL", "pl_teryt_terc", code, None, "codes/proposed/PL_powiaty.csv; gus_bdl_units_level5",
                        now_iso(fp.stat().st_mtime), official_check="match" if code in bdl else "not_in_official_list")
    fg = prop_dir / "PL_gmina_fill_reviewed.csv"
    if fg.exists():
        with fg.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                pid, code = (r.get("place_id") or "").strip(), (r.get("teryt") or "").strip()
                if r.get("decision") != "accept" or pid not in places or not re.fullmatch(r"\d{7}", code):
                    continue
                cur = (r.get("is_current") or "True") == "True"
                add(pid, "PL", "pl_teryt_terc", code, None,
                    "codes/proposed/PL_gmina_fill_reviewed.csv; eurostat_lau_2024 PL (TERC digits); pl.wikipedia TERC",
                    now_iso(fg.stat().st_mtime), is_current=cur, valid_to=r.get("valid_to") or None,
                    official_check=("match" if code[:6] in lau_pl6 else "not_in_official_list") if cur and lau_pl6 else None)
                for x in rows:
                    if (x["place_id"] == pid and x["code_system"] == "pl_teryt_terc" and len(x["code"]) == 7
                            and x["code"] != code and x["source"].startswith("wikidata") and lau_pl6
                            and x["code"][:6] not in lau_pl6):
                        x["official_check"] = "not_in_official_list"
                        conflicts.append({"place_id": pid, "country_code": "PL", "code_system": "pl_teryt_terc",
                                          "code": x["code"], "issue": "wikidata_code_not_in_official_list",
                                          "official_name": f"reviewed TERC {code}", "our_name": places[pid]["name"]})
    fgr = prop_dir / "GR_diavgeia_orgs.csv"
    if fgr.exists():
        with fgr.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                pid, uid = (r.get("place_id") or "").strip(), (r.get("diavgeia_uid") or "").strip()
                if pid in places and re.fullmatch(r"\d+", uid):
                    add(pid, "GR", "gr_diavgeia_org", uid, None,
                        "codes/proposed/GR_diavgeia_orgs.csv (diavgeia.gov.gr opendata organizations, " + r["status"] + ")",
                        now_iso(fgr.stat().st_mtime), official_check=None)
    #   - codes/proposed/GB_gss_reviewed.csv (decision=accept; 2026-10-17, ukie): gb_gss = ONS GSS code (9 chars,
    #     e.g. E06/E07/E08/E09/E10/E43/E04, W06/W04, S12, N09). Rows = Wikidata P836 values of our GB places checked
    #     against the ONS Code History Database June 2026 (cache/ons_chd_jun2026/ChangeHistory.csv); terminated codes
    #     carry is_current=False + valid_to. official_check = match (live in the CHD) / terminated / not_in_official_list.
    fgb = prop_dir / "GB_gss_reviewed.csv"
    if fgb.exists():
        chd_live, chd_any = set(), set()
        p_chd = CACHE / "ons_chd_jun2026" / "ChangeHistory.csv"
        if p_chd.exists():
            with p_chd.open(encoding="latin-1") as f:
                for r in csv.DictReader(f):
                    chd_any.add(r["GEOGCD"])
                    if r["STATUS"] == "live":
                        chd_live.add(r["GEOGCD"])
        with fgb.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                pid, code = (r.get("place_id") or "").strip(), (r.get("code") or "").strip()
                if r.get("decision") != "accept" or pid not in places or not re.fullmatch(r"[EWSNK]\d{8}", code):
                    continue
                cur = (r.get("is_current") or "True") == "True"
                chk = None
                if chd_any:
                    chk = ("match" if code in chd_live else "terminated" if code in chd_any else "not_in_official_list")
                add(pid, "GB", "gb_gss", code, "P836" if r.get("wikidata_p836") == "match" else None,
                    "codes/proposed/GB_gss_reviewed.csv; " + ("wikidata P836 + " if r.get("wikidata_p836") == "match" else "")
                    + "ons_chd_june_2026", now_iso(fgb.stat().st_mtime), is_current=cur,
                    valid_to=r.get("valid_to") or None, official_check=chk)
    # 2c) codes declared in place_additions.csv (official list values) when Wikidata did not supply them
    have0 = {(r["place_id"], r["code_system"], r["code"]) for r in rows if r["is_current"]}
    for p in places.values():
        if p.get("from") != "additions" or not p.get("official_code"):
            continue
        system, code = p["official_code_system"], p["official_code"]
        if (p["place_id"], system, code) not in have0:
            o = (off.get(system) or {}).get(code)
            add(p["place_id"], p["country_code"], system, code, None, "place_additions.csv: " + p["add_source"],
                now_iso(ADDITIONS.stat().st_mtime), official_check="match" if o else None)
    # 2e) KG: CBD (cbd.minjust.gov.kg) issuing-body id -> aiyl aimak place
    #     (codes_ext/build_kg_aiyl_aimaks.py; one row per resolved body, several bodies per place are normal)
    if KG_BODIES.exists():
        ra_kg = now_iso(KG_BODIES.stat().st_mtime)
        with KG_BODIES.open(encoding="utf-8") as f:
            for b in csv.DictReader(f):
                pid, bid = b["place_id"].strip(), b["cbd_issuing_body_id"].strip()
                if pid in places and bid:
                    add(pid, "KG", "kg_cbd_body", bid, None, "codes_ext/kg_body_to_place.csv (" + b["match"] + ")",
                        ra_kg, official_check=None)
    # 2d) NL waterschapscode (CBS/Het Waterschapshuis 4-digit) from the TOOI organisatiecode
    wsc = off.get("_nl_waterschapscode") or {}
    for r in list(rows):
        if r["code_system"] == "nl_tooi" and r["is_current"] and r["code"] in wsc:
            add(r["place_id"], "NL", "nl_waterschapscode", wsc[r["code"]], None,
                "derived:nl_tooi via tooi_rwc_waterschappen_compleet_2", r["retrieved_at"], official_check="match")

    # 3) gap fill from official lists by UNIQUE normalised name within the country (municipality-level places only)
    ra_off = now_iso()
    fill_sys = {"NL": "nl_cbs_gemeente", "CZ": "cz_ruian_obec", "HU": "hu_ksh", "AT": "at_gkz", "ES": "es_ine",
                "IT": "it_istat", "FR": "fr_insee_cog", "DE": "de_ags", "CH": "ch_bfs", "BR": "br_ibge",
                "CA": "ca_sgc_csd", "PH": "ph_psgc"}
    filled = collections.Counter()
    for cc, system in fill_sys.items():
        o = off.get(system) or {}
        names = collections.defaultdict(list)
        for code, (nm, src) in o.items():
            names[norm_name(nm)].append((code, src))
        ours = collections.defaultdict(list)
        for p in places.values():
            if p["country_code"] == cc and p["admin_level"] in ("municipality", "") and p["name"]:
                ours[norm_name(p["name"])].append(p)
        for p in places.values():
            if p["country_code"] != cc or system in have[p["place_id"]] or p["admin_level"] not in ("municipality",):
                continue
            n = norm_name(p["name"])
            cand = names.get(n) or []
            if len(cand) == 1 and len(ours.get(n, [])) == 1 and cand[0][0] not in used[system]:
                code, src = cand[0]
                add(p["place_id"], cc, system, code, None, f"official_name_match:{src}", ra_off,
                    official_check="name_match_only")
                have[p["place_id"]].add(system)
                used[system].add(code)
                filled[system] += 1
    # PE: UBIGEO by (department, province, district) names via Wikidata P131 chain
    pe_places = [p for p in places.values() if p["country_code"] == "PE" and p["qid"]]
    if off.get("_pe_full") and pe_places:
        vals = " ".join(f"wd:{p['qid']}" for p in pe_places)
        q = (PREFIX + "SELECT ?item ?l ?pl ?dl WHERE { VALUES ?item { " + vals + " } "
             "?item rdfs:label ?l . FILTER(LANG(?l)='es') "
             "OPTIONAL { ?item wdt:P131 ?prov . ?prov rdfs:label ?pl . FILTER(LANG(?pl)='es') "
             "OPTIONAL { ?prov wdt:P131 ?dep . ?dep rdfs:label ?dl . FILTER(LANG(?dl)='es') } } }")
        path = qlever(q, CACHE / "wd_PE_p131_labels.tsv", args.refresh)
        info = collections.defaultdict(lambda: {"l": set(), "pl": set(), "dl": set()})
        for it in read_tsv(path):
            it += [""] * 4
            info[it[0]]["l"].add(norm_name(it[1]))
            if it[2]:
                info[it[0]]["pl"].add(norm_name(re.sub(r"(?i)^provincia (de |del )?", "", it[2])))
            if it[3]:
                info[it[0]]["dl"].add(norm_name(re.sub(r"(?i)^(departamento|regi[oó]n) (de |del )?", "", it[3])))
        idx = collections.defaultdict(list)
        for code, (dist, src, dep, prov) in off["_pe_full"].items():
            idx[norm_name(dist)].append((code, norm_name(prov), norm_name(dep)))
        for p in pe_places:
            if "pe_ubigeo" in have[p["place_id"]] or p["admin_level"] != "municipality":
                continue
            inf = info.get(p["qid"])
            if not inf:
                continue
            cands = [c for n in inf["l"] | {norm_name(p["name"])} for c in idx.get(n, [])]
            cands = list({c[0]: c for c in cands}.values())
            if len(cands) > 1:
                cands = [c for c in cands if c[1] in inf["pl"] or c[2] in inf["dl"] or c[2] in inf["pl"]]
            if len(cands) > 1:
                cands = [c for c in cands if c[1] in inf["pl"]]
            if len(cands) == 1 and cands[0][0] not in used["pe_ubigeo"]:
                add(p["place_id"], "PE", "pe_ubigeo", cands[0][0], None, "official_name_match:inei_ubigeo_2022+wikidata_P131",
                    ra_off, official_check="name_match_only")
                have[p["place_id"]].add("pe_ubigeo")
                used["pe_ubigeo"].add(cands[0][0])
                filled["pe_ubigeo"] += 1
    print("gap-filled by name:", dict(filled))

    # 4) EU LAU + NUTS3 derived from national code via Eurostat LAU 2024
    natsys = {"nl_cbs_gemeente": "NL", "cz_ruian_obec": "CZ", "hu_ksh": "HU", "at_gkz": "AT", "es_ine": "ES",
              "it_istat": "IT", "fr_insee_cog": "FR", "de_ags": "DE", "ch_bfs": "CH"}
    for r in list(rows):
        cc = natsys.get(r["code_system"])
        if not cc or not r["is_current"]:
            continue
        lr = lau_by_nat.get((cc, r["code"]))
        if lr is None:
            continue
        lau = f'{cc}_{str(lr["LAU CODE"]).strip()}'
        add(r["place_id"], cc, "eu_lau", lau, None, f"eurostat_lau_2024 via {r['code_system']}", now_iso(),
            official_check="match")
        if lr.get("NUTS3"):
            add(r["place_id"], cc, "eu_nuts3", lr["NUTS3"], None, f"eurostat_lau_2024 via {r['code_system']}",
                now_iso(), official_check="match")
    # 5) US: Census GEOID from the candidate list (Census gazetteer)
    for p in places.values():
        if p["country_code"] == "US" and p["census_geoid"]:
            add(p["place_id"], "US", "us_census_geoid", p["census_geoid"], None, "global_municipalities_candidate.csv",
                now_iso(CANDIDATE.stat().st_mtime))

    # ---- write ----
    import pyarrow as pa
    import pyarrow.parquet as pq
    rows.sort(key=lambda r: (r["country_code"], r["place_id"], r["code_system"], r["code"]))
    cols = ["place_id", "country_code", "code_system", "code", "wikidata_property", "source", "retrieved_at",
            "is_current", "wd_rank", "valid_from", "valid_to", "official_check"]
    sch = pa.schema([(c, pa.bool_() if c == "is_current" else pa.string()) for c in cols])
    t = pa.Table.from_pylist(rows, schema=sch)
    pq.write_table(t, str(HERE / "place_codes.parquet"), compression="zstd")
    with (HERE / "place_codes.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    # wide (current codes only)
    wide = collections.defaultdict(dict)
    systems = sorted({r["code_system"] for r in rows})
    good = {(r["place_id"], r["code_system"]) for r in rows
            if r["is_current"] and r["official_check"] in ("match", "match_code_name_differs")}
    for r in rows:
        if r["is_current"] and not (r["official_check"] == "not_in_official_list"
                                    and (r["place_id"], r["code_system"]) in good):
            d = wide[r["place_id"]]
            d["country_code"] = r["country_code"]
            d[r["code_system"]] = ";".join(sorted(set(filter(None, (d.get(r["code_system"]) or "").split(";"))) | {r["code"]}))
    wrows = [{"place_id": k, **v} for k, v in sorted(wide.items())]
    wcols = ["place_id", "country_code"] + systems
    pq.write_table(pa.Table.from_pylist([{c: r.get(c) for c in wcols} for r in wrows],
                                        schema=pa.schema([(c, pa.string()) for c in wcols])),
                   str(HERE / "place_codes_wide.parquet"), compression="zstd")
    with (HERE / "place_codes_wide.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=wcols)
        w.writeheader()
        w.writerows(wrows)
    with (HERE / "conflicts.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["place_id", "country_code", "code_system", "code", "issue", "official_name", "our_name"])
        w.writeheader()
        w.writerows(conflicts)

    # ---- coverage ----
    cov = {}
    target = {s[0]: s[1] for s in SYSTEMS if s[1]}
    target.update({"jp_jis_x0402": "JP", "us_census_geoid": "US", "nl_waterschapscode": "NL", "kg_cbd_body": "KG",
                   "gr_diavgeia_org": "GR", "gb_gss": "GB"})
    muni = collections.Counter(p["country_code"] for p in places.values() if p["admin_level"] == "municipality")
    allp = collections.Counter(p["country_code"] for p in places.values())
    per = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.Counter()))
    for r in rows:
        if not r["is_current"]:
            continue
        c = per[r["country_code"]][r["code_system"]]
        c["places_" + ("wd" if r["source"].startswith("wikidata") else "derived" if r["source"].startswith(("derived", "eurostat")) else "name_match" if "name_match" in r["source"] else "other")] += 0
    pl_sets = collections.defaultdict(set)
    src_sets = collections.defaultdict(lambda: collections.Counter())
    chk = collections.defaultdict(lambda: collections.Counter())
    seen_ps = set()
    for r in rows:
        if not r["is_current"]:
            continue
        key = (r["country_code"], r["code_system"])
        if (key, r["place_id"]) in seen_ps:
            continue
        seen_ps.add((key, r["place_id"]))
        pl_sets[key].add(r["place_id"])
        s = r["source"]
        src_sets[key]["wikidata" if s.startswith("wikidata") else "name_match" if "name_match" in s else "derived" if s.startswith(("derived", "eurostat")) else "other"] += 1
        chk[key][r["official_check"] or "no_official_list"] += 1
    conf = collections.Counter((c["country_code"], c["code_system"], c["issue"]) for c in conflicts)
    for (cc, system), ps in sorted(pl_sets.items()):
        cov.setdefault(cc, {"places_total": allp[cc], "places_municipality": muni[cc], "systems": {}})
        cov[cc]["systems"][system] = {"places_with_code": len(ps), "by_source": dict(src_sets[(cc, system)]),
                                      "official_check": dict(chk[(cc, system)]),
                                      "conflicts": {k[2]: v for k, v in conf.items() if k[0] == cc and k[1] == system}}
    lvl = collections.defaultdict(collections.Counter)
    for p in places.values():
        lvl[p["country_code"]][p["admin_level"] or "unknown"] += 1
    for cc in cov:
        cov[cc]["places_by_admin_level"] = dict(lvl[cc].most_common())
    for system, cc in target.items():
        cov.setdefault(cc, {"places_total": allp[cc], "places_municipality": muni[cc], "systems": {}})
        cov[cc]["systems"].setdefault(system, {"places_with_code": 0})
    summary = {"built_at": now_iso(), "rows": len(rows), "places_with_any_code": len(wide),
               "places_in_list": len(places), "places_from_additions": n_add, "places_only_in_staging": n_stage,
               "official_sources": off_meta, "wikidata_source": QLEVER + " (dump latest-all.ttl 2026-08-10, live updates)",
               "coverage": cov}
    (HERE / "coverage.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    write_readme(summary, conflicts)
    print(f"wrote {len(rows)} rows, {len(wide)} places with codes, {len(conflicts)} conflicts")


GAPS = """- **PE**: Wikidata has UBIGEO (P844) on only ~50 of our districts. 1,829 were filled from INEI UBIGEO 2022
  by unique (district, province, department) name match, using the Wikidata P131 chain for the province and
  department (`official_check=name_match_only`).
- **PL**: about 440 items carry a 10-digit value under P1653 (GUS NTS-style, kept as `pl_nts`) instead of a
  7-digit TERC. No official TERC file was loaded, so 7-digit gmina codes are not cross-checked, and PL
  `eu_lau`/`eu_nuts3` aren't derived (Eurostat's PL LAU codes are 13 digits). The 380 current 4-digit powiat codes
  are complete and checked against GUS BDL (`1431` powiat warszawski in BDL was abolished in 2002).
- **NL**: Smallingerland, Opsterland, Weststellingwerf, Ooststellingwerf and Dantumadiel were dropped from the
  candidate CSV by `global_municipalities/clean_abolished.py` because their Wikidata items are also typed
  "former grietenij" (a historic Frisian class). They are restored through `place_additions.csv`. No other current
  NL municipality is missing (all 342 Eurostat LAU 2024 codes are covered). The 21 current water boards (TOOI)
  are places with `admin_level=water_board`; Blija Buitendijks (ws0202) ended 2017-12-20 and is not included.
- **MX, CL, ID**: no official list was loaded, so these are Wikidata-only and unchecked. CL CUT is on 300 of 358 communes.
- **IT**: about 140 Wikidata ISTAT codes in the 112–119 range (Sardinia's new provinces) are missing from the ISTAT
  list we downloaded, which still uses the old province codes. This is a timing conflict between Wikidata and
  ISTAT, not bad data. Expect it to clear on the next refresh of either source.
- **DE**: about 280 AGS on Wikidata are for municipalities merged away since 2019 (mostly Thuringia,
  Saxony-Anhalt and MV) that still have no end date. They are missing from Eurostat LAU 2024. Several of our
  candidate places are these former municipalities.
- **FR**: 34 codes are overseas collectivities (988xx New Caledonia, 977 Saint-Barthélemy, …), which are outside
  the COG commune file.
- **CH**: our list has more places than the 2,136 current BFS municipalities (former municipalities after mergers).
- **name_differs** rows are mostly exonyms or bilingual names ("Hamelin" vs "Hameln, Stadt", "Graun im
  Vinschgau" vs "Curon Venosta"). A few are real disagreements (e.g. ES 02034). See conflicts.csv.
- **CA**: `ca_sgc_csd` = Statistics Canada 2021 census subdivision code (CSDUID, 7 digits: province 2 + CD 2 +
  CSD 3), from Wikidata P3012 and checked against table 98-10-0002-01 (5,161 CSDs; `cache/statcan_csd_2021.csv`
  has the CSD type, e.g. CY/T/VL/MD/RM/TP/IRI, and the 2021 population). CSDs whose Wikidata item is not a candidate
  place are added through `place_additions.csv` (`admin_level=municipality`, or `indian_reserve` for IRI / S-É;
  parent = province, `iso_3166_2` = CA-XX; CSD type + population in `note`). Not added as places: unorganized and
  non-legislating CSD types NO, SNO, RDA, P (NB local service districts), SC, SÉ, SET, SA, TI, TC, TK, and the
  ~45 CSDs that have no Wikidata item. P3012 values with 2/4/6 digits (province / census division / other) are
  re-coded: a single-tier city that is one CSD (Toronto 3520 -> 3520005) gets its CSDUID by name match inside
  the census division; other values are kept under their SGC level instead: `ca_sgc_cd` (4-digit census division
  = county / regional district / regional municipality, e.g. Peel 3521, Metro Vancouver 5915), `ca_sgc_pr`
  (2-digit province/territory) and `ca_sgc_dpl` (6-digit designated place); P3012 codes of CSDs dissolved before 2021 are `not_in_official_list`. One QID
  can carry several CSDUIDs (PEI 'Part 1/2' pieces); all are listed.
- **GR**: `gr_diavgeia_org` covers only the 25 Diavgeia organisations resolved by hand in
  `codes/proposed/GR_diavgeia_orgs.csv` (the ones the scraper's name matcher misses, plus Chaidari 6313, which it
  matches to Hydra). The other ~312 orgs are matched at scrape time by `scrapers/eu/common/gr_names.py` and are not in
  this table yet.
- **US**: only the Census GEOID is included (from the candidate CSV), and not every gnis place has one.
"""


def write_readme(summary, conflicts):
    tpl = (HERE / "readme_template.md").read_text()
    lines = ["| country | places | muni | code_system | places with code | % of places | wikidata | name-match | derived | official check (match / name differs / not in list) |",
             "|---|---:|---:|---|---:|---:|---:|---:|---:|---|"]
    for cc, v in sorted(summary["coverage"].items()):
        for system, d in sorted(v["systems"].items()):
            n = d.get("places_with_code", 0)
            bs, oc = d.get("by_source", {}), d.get("official_check", {})
            pct = f"{100 * n / v['places_total']:.1f}%" if v["places_total"] else "n/a"
            chk = (f"{oc.get('match', 0)} / {oc.get('match_code_name_differs', 0)} / {oc.get('not_in_official_list', 0)}"
                   if any(k in oc for k in ("match", "not_in_official_list", "match_code_name_differs")) else "no official list")
            lines.append(f"| {cc} | {v['places_total']} | {v['places_municipality']} | `{system}` | {n} | {pct} | "
                         f"{bs.get('wikidata', 0)} | {bs.get('name_match', 0)} | {bs.get('derived', 0)} | {chk} |")
    offs = "\n".join(f"   - `{k}`: {u}" for k, u in sorted(summary["official_sources"].items()))
    (HERE / "README.md").write_text(tpl.replace("{built_at}", summary["built_at"])
                                    .replace("{wikidata_source}", summary["wikidata_source"])
                                    .replace("{official_sources}", offs)
                                    .replace("{coverage_table}", "\n".join(lines))
                                    .replace("{gaps}", GAPS))


if __name__ == "__main__":
    main()
