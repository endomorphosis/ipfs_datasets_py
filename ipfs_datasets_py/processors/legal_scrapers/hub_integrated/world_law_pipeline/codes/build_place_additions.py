#!/usr/bin/env python3
"""Build codes/place_additions.csv: places that are NOT in global_municipalities_candidate.csv but that our bots
publish law for. build_place_codes.py reads this file alongside the candidate CSV (the candidate CSV is never
modified; a place_id already present in the candidate CSV is ignored here).

Inputs (all cached under cache/, re-fetch with --refresh; Wikidata via QLever, never query.wikidata.org):
  wd_pl_powiaty.tsv          Wikidata items P31 powiat (Q247073) / city with powiat rights (Q925381), labels, P131 voivodeship + P300
  wd_P1653.tsv               Wikidata TERYT (P1653) statements (shared with build_place_codes.py)
  gus_bdl_powiaty.json       GUS Bank Danych Lokalnych units level 5 (all powiats incl. cities), official
  wd_nl_waterschappen.tsv    Wikidata items with TOOI identifier waterschap/ws#### and no P576
  tooi_rwc_waterschappen_compleet_2.json  TOOI waardelijst "waterschappen compleet" v2 (KOOP / BZK), official
  wd_nl_frisian_munis.tsv    labels + CBS code for the 5 Frisian municipalities dropped from the candidate list
  statcan_98100002_csd_2021.zip  Statistics Canada table 98-10-0002-01 (2021 Census population and dwelling counts,
                             Canada and census subdivisions), official; parsed to statcan_csd_2021.csv
                             (csduid, name, csd_type, csd_type_desc, pr_code, prov_abbr, population_2021)
  wd_P3012.tsv               Wikidata Statistics Canada Geographic code (P3012) statements (shared with build_place_codes.py)

Added:
  PL  admin_level=county      the 314 land powiats (powiat ziemski), place_id wd:Q…, parent = voivodeship.
      The 66 cities with powiat rights are already candidate places (admin_level=municipality); they get their
      4-digit powiat TERYT code in place_codes (P1653 or derived from the 7-digit TERC) instead of a new place.
  NL  admin_level=water_board the 21 current waterschappen (TOOI list, cross-checked with Wikidata P11767).
  NL  admin_level=municipality Smallingerland, Opsterland, Weststellingwerf, Ooststellingwerf, Dantumadiel
      (removed from the candidate list by clean_abolished.py because Wikidata also types them "former grietenij").
  KG  admin_level=municipality aiyl aimaks without a Wikidata item: place_id KG-kg_cbd:<CBD organ id> from
      codes/proposed/KG_aiyl_aimaks.csv (id_scheme=kg_cbd), official_code_system=kg_cbd_body; minus nonstandard
      (typo-variant) organ ids, ambiguous bodies and ids outside [0-9A-Za-z-]+. Dotted organ ids skipped there are
      added from codes/proposed/KG_aiyl_aimaks_dotted.csv with dots replaced by "-" (proposed_organ_id). A later
      QID goes into qid (alias).
  CA  2021 Census subdivisions (CSD) whose Wikidata item (P3012 = 7-digit CSDUID) is not yet a candidate place:
      admin_level=municipality for municipal CSD types, admin_level=indian_reserve for IRI / S-É; parent = province,
      iso_3166_2 = CA-XX, official_code_system=ca_sgc_csd, official_code=CSDUID, note = CSD type + 2021 population.
      Not added (non-legislating / unorganized): NO, SNO, RDA (BC electoral areas), P (NB parishes = local service
      districts), SC (NS subdivisions of county municipality), SÉ (YT), SET (NT/NU), SA (AB special areas),
      TI / TC / TK (Inuit / Cree / Naskapi category-I lands; the VN / VC / VK municipality is added instead).
  PL  admin_level=municipality gminas from codes/proposed/PL_gmina_fill_reviewed.csv (decision=accept) whose place is not
      a candidate: Wąbrzeźno town (urban gmina TERC 0417011, wd:Q324912) and the former rural gmina Ostrowice
      (wd:Q557603, TERC 3203042, dissolved 2019-01-01; note starts with "former:", successors in place_successors.csv).
  GR  admin_level=municipality former municipalities (2011-2019, split by Law 4600/2019 from 2019-09-01) that Diavgeia
      still lists as issuing organisations: codes/proposed/GR_diavgeia_orgs.csv status=new (Corfu, Kefalonia, Lesvos,
      Samos); official_code_system=gr_diavgeia_org, official_code = Diavgeia organisation uid; note starts with
      "former:", successors in place_successors.csv.
  GB  admin_level=region      Greater London wd:Q23306 (GB_MANUAL, gb_gss E12000007): London-wide local Acts.
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
import collections
import csv
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
OUT = HERE / "place_additions.csv"
AUDIT = HERE / "former_type_audit.csv"
CANDIDATE = Path(os.environ.get("GLOBAL_MUNICIPALITIES_CSV", "/workspace/global_municipalities/global_municipalities_candidate.csv"))
QLEVER = "https://qlever.dev/api/wikidata"
UA = "world-law-place-codes/0.1 (Benjamin Barber; low volume; bulk via QLever)"
COLS = ["place_id", "country_code", "name", "name_native", "admin_level", "parent_place_id", "iso_3166_2", "qid",
        "official_code_system", "official_code", "source", "note"]
P = ("PREFIX wdt: <http://www.wikidata.org/prop/direct/> PREFIX wd: <http://www.wikidata.org/entity/> "
     "PREFIX p: <http://www.wikidata.org/prop/> PREFIX ps: <http://www.wikidata.org/prop/statement/> "
     "PREFIX pq: <http://www.wikidata.org/prop/qualifier/> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> ")
QUERIES = {
    "wd_pl_powiaty.tsv": P + """SELECT ?item ?cls ?pl ?en (SAMPLE(?d) AS ?dissolved) (SAMPLE(?iso) AS ?iso2) (SAMPLE(?vq) AS ?voiv) WHERE {
 VALUES ?cls { wd:Q247073 wd:Q925381 } ?item p:P31 ?st . ?st ps:P31 ?cls . FILTER NOT EXISTS { ?st pq:P582 ?e0 }
 OPTIONAL { ?item rdfs:label ?pl FILTER(LANG(?pl)="pl") } OPTIONAL { ?item rdfs:label ?en FILTER(LANG(?en)="en") }
 OPTIONAL { ?item wdt:P576 ?d } OPTIONAL { ?item wdt:P131 ?vq . ?vq wdt:P31 wd:Q150093 . OPTIONAL { ?vq wdt:P300 ?iso } }
} GROUP BY ?item ?cls ?pl ?en""",
    "wd_nl_waterschappen.tsv": P + """SELECT ?i ?nl ?en ?tooi ?kvk WHERE { ?i wdt:P11767 ?tooi . FILTER(STRSTARTS(?tooi,"waterschap/"))
 OPTIONAL { ?i rdfs:label ?nl FILTER(LANG(?nl)="nl") } OPTIONAL { ?i rdfs:label ?en FILTER(LANG(?en)="en") }
 OPTIONAL { ?i wdt:P3220 ?kvk } FILTER NOT EXISTS { ?i wdt:P576 ?d } }""",
    "wd_nl_frisian_munis.tsv": P + """SELECT ?i ?nl ?en ?fy ?cbs WHERE { VALUES ?i { wd:Q507065 wd:Q840632 wd:Q753913 wd:Q259205 wd:Q389213 }
 OPTIONAL { ?i rdfs:label ?nl FILTER(LANG(?nl)="nl") } OPTIONAL { ?i rdfs:label ?en FILTER(LANG(?en)="en") }
 OPTIONAL { ?i rdfs:label ?fy FILTER(LANG(?fy)="fy") } OPTIONAL { ?i wdt:P382 ?cbs } }""",
}
URLS = {
    "statcan_98100002_csd_2021.zip": "https://www150.statcan.gc.ca/n1/tbl/csv/98100002-eng.zip",
    "gus_bdl_powiaty.json": "https://bdl.stat.gov.pl/api/v1/units?level=5&page-size=100&format=json&page={page}",
    "tooi_rwc_waterschappen_compleet_2.json": "https://repository.officiele-overheidspublicaties.nl/waardelijsten/"
                                              "rwc_waterschappen_compleet/2/json/rwc_waterschappen_compleet_2.json",
}
# ---- CA (Statistics Canada SGC 2021)
CA_PROV = {"10": ("CA-NL", "Q2003"), "11": ("CA-PE", "Q1978"), "12": ("CA-NS", "Q1952"), "13": ("CA-NB", "Q1965"),
           "24": ("CA-QC", "Q176"), "35": ("CA-ON", "Q1904"), "46": ("CA-MB", "Q1948"), "47": ("CA-SK", "Q1989"),
           "48": ("CA-AB", "Q1951"), "59": ("CA-BC", "Q1973"), "60": ("CA-YT", "Q2009"), "61": ("CA-NT", "Q2007"),
           "62": ("CA-NU", "Q2023")}   # P300 / P3012 verified on QLever 2026-10-12
CA_RESERVE = {"IRI", "S-É"}
CA_EXCLUDED = {"NO", "SNO", "RDA", "P", "SC", "SÉ", "SET", "SA", "TI", "TC", "TK"}
CA_CSV = CACHE / "statcan_csd_2021.csv"
CA_COLS = ["csduid", "name", "csd_type", "csd_type_desc", "pr_code", "prov_abbr", "population_2021"]


def ca_csd_list():
    """Statistics Canada 98-10-0002-01 -> list of 2021 CSDs (cached as statcan_csd_2021.csv)."""
    if not CA_CSV.exists():
        import io
        import zipfile
        z = zipfile.ZipFile(CACHE / "statcan_98100002_csd_2021.zip")
        attrs = collections.defaultdict(dict)
        for r in csv.reader(io.TextIOWrapper(z.open("98100002_MetaData.csv"), encoding="utf-8-sig")):
            if len(r) == 7 and r[0] == "1" and r[1].isdigit():
                attrs[r[1]][r[3]] = r[6]
        pop = {r["DGUID"]: r["Population and dwelling counts (13): Population, 2021 [1]"]
               for r in csv.DictReader(io.TextIOWrapper(z.open("98100002.csv"), encoding="utf-8-sig"))}
        out = [{"csduid": d["ALT_GEO_CODE"], "name": d["GEO_NAME"], "csd_type": d["GEO_TYPE_ABBR"],
                "csd_type_desc": d["GEO_TYPE_DESC"], "pr_code": d["PR_CODE"], "prov_abbr": d["PROV_ABBR"],
                "population_2021": pop.get(d["DGUID"], "")}
               for d in attrs.values() if d.get("GEO_LEVEL_DESC") == "Census subdivision"]
        out.sort(key=lambda r: r["csduid"])
        tmp = CA_CSV.with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CA_COLS)
            w.writeheader()
            w.writerows(out)
        tmp.replace(CA_CSV)
    with CA_CSV.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def p3012():
    d = collections.defaultdict(set)
    for r in tsv("wd_P3012.tsv"):
        if "Deprecated" not in r.get("rank", "") and not r.get("end") and re.fullmatch(r"\d{7}", r["v"]):
            d[r["v"]].add(r["item"])
    return d


def ph_cities():
    """cache/ph_cities.jsonl = copy of /workspace/world_law/codes_ext/ph_cities.jsonl (codes_ext/build_ph_cities.py)."""
    p = CACHE / "ph_cities.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.open(encoding="utf-8") if line.strip()]


FRISIAN = {"Q507065", "Q840632", "Q753913", "Q259205", "Q389213"}


def curl(args):
    subprocess.run(["curl", "-sS", "-L", "-m", "600", "--retry", "3", "--retry-delay", "20", "-A", UA] + args, check=True)


def refresh():
    for fn, q in QUERIES.items():
        tmp = CACHE / (fn + ".tmp")
        curl(["-H", "Accept: text/tab-separated-values", "--data-urlencode", f"query={q}", QLEVER, "-o", str(tmp)])
        tmp.replace(CACHE / fn)
        time.sleep(1)
    res = []
    for page in range(10):
        tmp = CACHE / "bdl_page.tmp"
        curl([URLS["gus_bdl_powiaty.json"].format(page=page), "-o", str(tmp)])
        d = json.loads(tmp.read_text())
        res += d["results"]
        tmp.unlink()
        if len(res) >= d["totalRecords"]:
            break
        time.sleep(2)
    out = [{"teryt": r["id"][2:4] + r["id"][7:9], "name": r["name"], "kind": r["kind"], "bdl_id": r["id"]} for r in res]
    (CACHE / "gus_bdl_powiaty.json").write_text(json.dumps(out, ensure_ascii=False, indent=0))
    tmp = CACHE / "tooi.tmp"
    curl([URLS["tooi_rwc_waterschappen_compleet_2.json"], "-o", str(tmp)])
    tmp.replace(CACHE / "tooi_rwc_waterschappen_compleet_2.json")
    tmp = CACHE / "statcan.tmp"
    curl([URLS["statcan_98100002_csd_2021.zip"], "-o", str(tmp)])
    tmp.replace(CACHE / "statcan_98100002_csd_2021.zip")
    CA_CSV.unlink(missing_ok=True)
    import build_place_codes as BPC
    BPC.fetch_prop("P3012", True)


def uq(s):
    s = s.strip()
    return s.strip("<>").rsplit("/", 1)[-1] if s.startswith("<") else re.sub(r'^"|"(\^\^.*|@[a-z\-]+)?$', "", s)


def tsv(fn):
    with (CACHE / fn).open(encoding="utf-8") as f:
        hdr = [h.lstrip("?") for h in next(f).rstrip("\n").split("\t")]
        for line in f:
            vals = [uq(x) for x in line.rstrip("\n").split("\t")]
            yield dict(zip(hdr, vals + [""] * (len(hdr) - len(vals))))


def p1653():
    d = collections.defaultdict(list)
    for r in tsv("wd_P1653.tsv"):
        if "Deprecated" not in r.get("rank", ""):
            d[r["item"]].append((r["v"], r.get("end", "")))
    return d


def tooi_current():
    T = "https://identifier.overheid.nl/tooi/def/ont/"
    out = {}
    for x in json.loads((CACHE / "tooi_rwc_waterschappen_compleet_2.json").read_text()):
        if "HistorischeVersie" in str(x.get("@type")) or not x["@id"].rsplit("/", 1)[-1].startswith("ws"):
            continue
        g = lambda k: (x.get(T + k) or [{}])[0].get("@value")
        if g("einddatum"):
            continue
        out[g("organisatiecode")] = {"name": g("officieleNaamInclSoort"), "waterschapscode": g("waterschapscode"),
                                     "begin": g("begindatum")}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    if args.refresh:
        refresh()
    cand = set()
    with CANDIDATE.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cand.add(r["place_id"].strip())
            if (r.get("qid") or "").strip():
                cand.add("wd:" + r["qid"].strip())
    rows, problems = [], []
    # ---- PL powiats
    bdl = {o["teryt"]: o for o in json.loads((CACHE / "gus_bdl_powiaty.json").read_text())}
    ter = p1653()
    items = collections.defaultdict(lambda: {"cls": set()})
    for r in tsv("wd_pl_powiaty.tsv"):
        it = items[r["item"]]
        it["cls"].add(r["cls"])
        for k in ("pl", "en", "dissolved", "iso2", "voiv"):
            it[k] = it.get(k) or r.get(k, "")
    seen_codes = {}
    for q, it in sorted(items.items()):
        if "Q247073" not in it["cls"] or it["dissolved"]:
            continue
        codes = sorted({v for v, e in ter.get(q, []) if len(v) == 4 and v.isdigit() and not e})
        if len(codes) != 1:
            if codes or it["iso2"]:
                problems.append((q, it["pl"], "powiat_without_single_current_4digit_teryt", codes))
            continue
        code = codes[0]
        b = bdl.get(code)
        if not b:
            problems.append((q, it["pl"], "teryt_not_in_gus_bdl", code))
            continue
        if code in seen_codes:
            problems.append((q, it["pl"], "duplicate_teryt", code, seen_codes[code]))
            continue
        seen_codes[code] = q
        pid = f"wd:{q}"
        if pid in cand:
            continue
        rows.append({"place_id": pid, "country_code": "PL", "name": it["en"] or it["pl"], "name_native": it["pl"],
                     "admin_level": "county", "parent_place_id": f"wd:{it['voiv']}" if it["voiv"] else "",
                     "iso_3166_2": it["iso2"], "qid": q, "official_code_system": "pl_teryt_terc",
                     "official_code": code, "source": "wikidata(qlever) P31=Q247073 + P1653; gus_bdl units level 5",
                     "note": f"GUS BDL: {b['name']} ({b['bdl_id']})"})
    # ---- NL water boards
    tooi = tooi_current()
    wd_ws = {}
    for r in tsv("wd_nl_waterschappen.tsv"):
        wd_ws.setdefault(r["tooi"].split("/", 1)[-1], r)
    for code, t in sorted(tooi.items()):
        w = wd_ws.get(code)
        if not w:
            problems.append(("", t["name"], "tooi_waterschap_without_wikidata_item", code))
            continue
        pid = f"wd:{w['i']}"
        if pid in cand:
            continue
        rows.append({"place_id": pid, "country_code": "NL", "name": w["en"] or w["nl"], "name_native": t["name"],
                     "admin_level": "water_board", "parent_place_id": "iso:NL", "iso_3166_2": "", "qid": w["i"],
                     "official_code_system": "nl_tooi", "official_code": code,
                     "source": "TOOI rwc_waterschappen_compleet v2 + wikidata(qlever) P11767",
                     "note": f"waterschapscode {t['waterschapscode']}; KvK {w.get('kvk') or '-'}"})
    for code in sorted(set(wd_ws) - set(tooi)):
        problems.append((wd_ws[code]["i"], wd_ws[code]["nl"], "wikidata_waterschap_not_current_in_tooi", code))
    # ---- NL Frisian municipalities
    for r in tsv("wd_nl_frisian_munis.tsv"):
        pid = f"wd:{r['i']}"
        if pid in cand or r["i"] not in FRISIAN:
            continue
        rows.append({"place_id": pid, "country_code": "NL", "name": r["en"] or r["nl"],
                     "name_native": r["nl"] + (f" / {r['fy']}" if r["fy"] and r["fy"] != r["nl"] else ""),
                     "admin_level": "municipality", "parent_place_id": "wd:Q770", "iso_3166_2": "NL-FR", "qid": r["i"],
                     "official_code_system": "nl_cbs_gemeente", "official_code": r["cbs"],
                     "source": "wikidata(qlever) P382; eurostat_lau_2024 NL",
                     "note": "restored: former-type false positive (clean_abolished.py dropped it; Wikidata P31 also 'former grietenij')"})
    # ---- BE/EE current municipalities missing from the candidate list (successor targets of place_successors.csv)
    import build_place_successors as BS
    miss, unmapped = BS.current_missing()
    for r in miss:
        if r["place_id"] not in cand and r["place_id"] not in {x["place_id"] for x in rows}:
            rows.append(r)
    for cc, code, name in unmapped:
        problems.append(("", name, f"{cc} current municipality without a Wikidata item", code))
    # ---- restored former-type false positives (audit_former_types.py -> former_type_audit.csv, status=restore)
    have = {r["place_id"] for r in rows}
    if AUDIT.exists():
        with AUDIT.open(encoding="utf-8") as f:
            for a in csv.DictReader(f):
                if a["status"] != "restore" or a["place_id"] in cand or a["place_id"] in have:
                    continue
                have.add(a["place_id"])
                rows.append({"place_id": a["place_id"], "country_code": a["country_code"], "name": a["name"],
                             "name_native": "", "admin_level": a["admin_level"], "parent_place_id": "",
                             "iso_3166_2": a["iso_3166_2"], "qid": a["qid"],
                             "official_code_system": a["official_code_system"], "official_code": a["official_code"],
                             "source": "former_type_audit.csv (QLever P576/P1366 + " + a["evidence"].split(": ", 1)[-1] + ")",
                             "note": "restored: former-type false positive (" + a["removal_reason"] + ")"})
    else:
        problems.append(("", "", "former_type_audit.csv missing; run audit_former_types.py", ""))
    # ---- CA: 2021 Census subdivisions (Statistics Canada) joined to Wikidata via P3012
    have = {r["place_id"] for r in rows}
    wd_csd = p3012()
    ca_rows = {}
    for c in ca_csd_list():
        if c["csd_type"] in CA_EXCLUDED:
            continue
        qs = sorted(wd_csd.get(c["csduid"], ()), key=lambda q: int(q[1:]))
        if not qs:
            problems.append(("", c["name"], "CA CSD without a Wikidata item (P3012)", c["csduid"], c["csd_type"]))
            continue
        if any(f"wd:{q}" in cand for q in qs):
            continue
        q = qs[0]
        if len(qs) > 1:
            problems.append((q, c["name"], "CA CSD with several Wikidata items, lowest QID used", c["csduid"], qs))
        pid = f"wd:{q}"
        if pid in have:
            continue
        iso, prq = CA_PROV[c["pr_code"]]
        if pid in ca_rows:   # one Wikidata item for several CSDs (PEI 'Part 1/2' pieces): keep the first CSDUID
            ca_rows[pid]["note"] += f"; also CSD {c['csduid']} {c['name']} ({c['csd_type']}, pop 2021 {c['population_2021']})"
            continue
        ca_rows[pid] = {"place_id": pid, "country_code": "CA", "name": c["name"], "name_native": "",
                        "admin_level": "indian_reserve" if c["csd_type"] in CA_RESERVE else "municipality",
                        "parent_place_id": f"wd:{prq}", "iso_3166_2": iso, "qid": q,
                        "official_code_system": "ca_sgc_csd", "official_code": c["csduid"],
                        "source": "statcan 98-10-0002-01 (2021 census subdivisions) + wikidata(qlever) P3012",
                        "note": f"CSD type {c['csd_type']} ({c['csd_type_desc']}); pop 2021 {c['population_2021']}"}
    rows += ca_rows.values()
    # ---- PH: the 149 cities (HUC/ICC/CC), not in the candidate list (which has PH municipalities/provinces/regions)
    have = {r["place_id"] for r in rows}
    for c in ph_cities():
        pid = c["place_id"]
        if pid in cand or pid in have:
            continue
        par = (c.get("province_qid") or "").split("; ")[0] or (c.get("region_qid") or "").split("; ")[0]
        rows.append({"place_id": pid, "country_code": "PH", "name": c["name"], "name_native": c.get("psa_name") or "",
                     "admin_level": "municipality", "parent_place_id": f"wd:{par}" if par else "", "iso_3166_2": "",
                     "qid": c["qid"], "official_code_system": "ph_psgc", "official_code": c["psgc_code"],
                     "source": "wikidata(qlever) P31 Q29946056/Q106079704/Q106078286 + PSA PSGC 1Q 2026 publication datafile",
                     "note": f"city_class {c['city_class']}; province {c.get('province') or '-'}; region {c.get('region') or '-'}"})
    # ---- KG: aiyl aimaks resolved from CBD issuing bodies (codes_ext/build_kg_aiyl_aimaks.py) to a wd: id; bodies
    #      without a QID are added further below as KG-kg_cbd:<organ id> places (kg_cbd_rows).
    have = {r["place_id"] for r in rows}
    kg = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/codes_ext/kg_body_to_place.csv"))
    if kg.exists():
        with kg.open(encoding="utf-8") as f:
            for b in csv.DictReader(f):
                pid = b["place_id"].strip()
                if not pid.startswith("wd:Q") or pid in cand or pid in have:
                    continue
                have.add(pid)
                rows.append({"place_id": pid, "country_code": "KG", "name": b["name"], "name_native": b["name"],
                             "admin_level": "municipality", "parent_place_id": "",
                             "iso_3166_2": b.get("region_code") or "", "qid": pid[3:],
                             "official_code_system": "kg_cbd_body", "official_code": b["cbd_issuing_body_id"],
                             "source": "codes/proposed/KG_aiyl_aimaks.csv (CBD issuing bodies) via codes_ext/build_kg_aiyl_aimaks.py",
                             "note": f"aiyl aimak; district {b['parent'] or '-'}; match {b['match']}"})
    # ---- KG: councils without a Wikidata item, keyed by their CBD issuing-organ id (place_id KG-kg_cbd:<organ id>,
    #      approved 2026-10-16). Source rows: codes/proposed/KG_aiyl_aimaks.csv with id_scheme=kg_cbd. Left out:
    #      cbd_id_flag=nonstandard (typo variants of another organ id), the ambiguous bodies
    #      (codes_ext/kg_body_ambiguous.csv). Organ ids with dots are added from KG_aiyl_aimaks_dotted.csv
    #      (proposed_organ_id = dots replaced by "-"; approved 2026-10-16). The id is permanent: a Wikidata QID
    #      found later is written to the qid column (alias), the place_id stays.
    have_kg = {r["place_id"] for r in rows} | set(cand)
    rows += kg_cbd_rows(have_kg, problems)
    rows += kg_cbd_dotted_rows(have_kg, problems)
    # ---- PL gminas + GR (former) municipalities missing from the candidate list (reviewed 2026-10-17, plgr)
    rows += pl_gr_rows(cand, {r["place_id"] for r in rows}, problems)
    # ---- GB: reviewed single additions (2026-10-17, ukie; Benjamin's decision): Greater London as ONE region place
    #      (not a copy per borough) for London-wide local Acts (London Local Authorities Acts, TfL Acts, GLA bodies).
    have = {r["place_id"] for r in rows}
    for g in GB_MANUAL:
        if g["place_id"] in cand or g["place_id"] in have:
            continue
        rows.append(dict(g))
    rows.sort(key=lambda r: (r["country_code"], r["admin_level"], r["place_id"]))
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(OUT)
    print(f"wrote {OUT} rows={len(rows)}", dict(collections.Counter((r['country_code'], r['admin_level']) for r in rows)))
    for p in problems:
        print("  problem:", p, file=sys.stderr)


KG_PROPOSED = Path(os.environ.get("KG_AIYL_AIMAKS_CSV", "/workspace/world_law/codes/proposed/KG_aiyl_aimaks.csv"))
KG_DOTTED = Path(os.environ.get("KG_AIYL_AIMAKS_DOTTED_CSV",
                                "/workspace/world_law/codes/proposed/KG_aiyl_aimaks_dotted.csv"))
KG_AMBIGUOUS = Path(os.environ.get("KG_BODY_AMBIGUOUS_CSV", "/workspace/world_law/codes_ext/kg_body_ambiguous.csv"))
KG_CBD_SOURCE = "codes/proposed/KG_aiyl_aimaks.csv (id_scheme=kg_cbd; CBD cbd.minjust.gov.kg issuing organ)"
KG_DOTTED_SOURCE = ("codes/proposed/KG_aiyl_aimaks_dotted.csv "
                    "(id_scheme=kg_cbd; dotted CBD organ id -> dashed proposed_organ_id)")


def kg_cbd_rows(have: set, problems: list, proposed: Path = None, ambiguous: Path = None, stats: dict = None) -> list:
    """place_additions rows for the approved KG-kg_cbd:<organ id> places (see the KG block in main())."""
    sys.path.insert(0, str(HERE.parent))
    import schema as S
    proposed, ambiguous = proposed or KG_PROPOSED, ambiguous or KG_AMBIGUOUS
    st = collections.Counter() if stats is None else stats
    if not proposed.exists():
        problems.append(("", "", f"{proposed} missing; no KG-kg_cbd places added", ""))
        return []
    amb = set()
    if ambiguous.exists():
        with ambiguous.open(encoding="utf-8") as f:
            amb = {r["cbd_issuing_body_id"].strip() for r in csv.DictReader(f) if r.get("cbd_issuing_body_id")}
    out = []
    with proposed.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("id_scheme") or "").strip() != "kg_cbd":
                continue
            st["kg_cbd_rows"] += 1
            oid = (r.get("cbd_organ_id") or "").strip()
            flag = (r.get("cbd_id_flag") or "").strip()
            name = (r.get("aiyl_aimak_ru") or "").strip() or (r.get("cbd_name_ru_raw") or "").strip()
            if "nonstandard" in flag:
                st["kg_cbd_skip_nonstandard"] += 1
                continue
            body_ids = {oid, (r.get("cbd_issuing_body_id") or "").strip()} | {
                x.strip() for x in (r.get("merged_from_body_ids") or "").split("|") if x.strip()}
            if body_ids & amb:
                st["kg_cbd_skip_ambiguous"] += 1
                continue
            try:
                pid = S.kg_cbd_place_id(oid)
            except ValueError:
                st["kg_cbd_skip_bad_organ_id"] += 1
                problems.append((r.get("proposed_place_id", ""), name, "KG kg_cbd organ id not [0-9A-Za-z-]+; not added", oid))
                continue
            if (r.get("proposed_place_id") or "").strip() not in ("", pid):
                st["kg_cbd_skip_id_mismatch"] += 1
                problems.append((r["proposed_place_id"], name, "KG proposed_place_id != KG-kg_cbd:<cbd_organ_id>", oid))
                continue
            if pid in have:
                st["kg_cbd_skip_duplicate"] += 1
                continue
            have.add(pid)
            iso = (r.get("parent_oblast_iso") or "").strip()
            out.append({"place_id": pid, "country_code": "KG", "name": name,
                        "name_native": (r.get("aiyl_aimak_ky") or "").strip() or (r.get("cbd_name_ky_raw") or "").strip(),
                        "admin_level": "municipality", "parent_place_id": "",
                        "iso_3166_2": iso if re.fullmatch(r"KG-[A-Z]", iso) else "", "qid": "",
                        "official_code_system": "kg_cbd_body", "official_code": oid, "source": KG_CBD_SOURCE,
                        "note": "aiyl aimak (no Wikidata item; id = CBD organ id); rayon "
                                f"{(r.get('parent_rayon') or '').strip() or '-'}; oblast "
                                f"{(r.get('parent_oblast') or '').strip() or '-'}"
                                + (f"; cbd_id_flag {flag}" if flag else "")})
            st["kg_cbd_added"] += 1
    print("KG kg_cbd:", dict(st))
    return out



def kg_cbd_dotted_rows(have: set, problems: list, dotted: Path = None, stats: dict = None) -> list:
    """place_additions rows for dotted CBD organ ids (approved dashed replacements in KG_aiyl_aimaks_dotted.csv).

    Uses proposed_organ_id as the organ id / official_code; keeps the original dotted id in note.
    Skips duplicates and place_key collisions against `have` (mutated as rows are added).
    """
    sys.path.insert(0, str(HERE.parent))
    import schema as S
    dotted = dotted or KG_DOTTED
    st = collections.Counter() if stats is None else stats
    if not dotted.exists():
        problems.append(("", "", f"{dotted} missing; no KG-kg_cbd dotted places added", ""))
        return []
    keys = set()
    for pid in have:
        try:
            keys.add(S.place_key(pid))
        except ValueError:
            pass
    out = []
    with dotted.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("id_scheme") or "").strip() != "kg_cbd":
                continue
            st["kg_cbd_dotted_rows"] += 1
            src_oid = (r.get("cbd_organ_id") or "").strip()
            oid = (r.get("proposed_organ_id") or "").strip()
            name = (r.get("cbd_name_ru_raw") or "").strip() or (r.get("cbd_name_ky_raw") or "").strip()
            coll = (r.get("collision") or "").strip()
            if coll and coll.lower() not in ("", "0", "false", "no", "none"):
                st["kg_cbd_dotted_skip_collision_flag"] += 1
                problems.append((r.get("proposed_place_id", ""), name,
                                 "KG dotted row collision flag set; not added", f"{src_oid}->{oid}:{coll}"))
                continue
            if not oid:
                st["kg_cbd_dotted_skip_empty"] += 1
                problems.append((r.get("proposed_place_id", ""), name,
                                 "KG dotted row missing proposed_organ_id", src_oid))
                continue
            try:
                pid = S.kg_cbd_place_id(oid)
            except ValueError:
                st["kg_cbd_dotted_skip_bad_organ_id"] += 1
                problems.append((r.get("proposed_place_id", ""), name,
                                 "KG dotted proposed_organ_id not [0-9A-Za-z-]+; not added", f"{src_oid}->{oid}"))
                continue
            if (r.get("proposed_place_id") or "").strip() != pid:
                st["kg_cbd_dotted_skip_id_mismatch"] += 1
                problems.append((r.get("proposed_place_id", ""), name,
                                 "KG proposed_place_id != S.kg_cbd_place_id(proposed_organ_id)", f"{src_oid}->{oid}"))
                continue
            try:
                pk = S.place_key(pid)
            except ValueError as e:
                st["kg_cbd_dotted_skip_bad_key"] += 1
                problems.append((pid, name, f"KG place_key failed: {e}", f"{src_oid}->{oid}"))
                continue
            if (r.get("proposed_place_key") or "").strip() not in ("", pk):
                st["kg_cbd_dotted_skip_key_mismatch"] += 1
                problems.append((pid, name, "KG proposed_place_key != place_key(proposed_place_id)",
                                 f"{r.get('proposed_place_key')!s} vs {pk}"))
                continue
            if pid in have:
                st["kg_cbd_dotted_skip_duplicate"] += 1
                problems.append((pid, name, "KG dotted place_id already present; not added", f"{src_oid}->{oid}"))
                continue
            if pk in keys:
                st["kg_cbd_dotted_skip_key_collision"] += 1
                problems.append((pid, name, "KG dotted place_key collides with existing place; not added", pk))
                continue
            have.add(pid)
            keys.add(pk)
            iso = (r.get("parent_oblast_iso") or "").strip()
            note = ("aiyl aimak (no Wikidata item; id = CBD organ id with dots->dashes); "
                    f"source organ id {src_oid}; rayon "
                    f"{(r.get('parent_rayon') or '').strip() or '-'}; oblast "
                    f"{(r.get('parent_oblast') or '').strip() or '-'}")
            out.append({"place_id": pid, "country_code": "KG", "name": name,
                        "name_native": (r.get("cbd_name_ky_raw") or "").strip(),
                        "admin_level": "municipality", "parent_place_id": "",
                        "iso_3166_2": iso if re.fullmatch(r"KG-[A-Z]", iso) else "", "qid": "",
                        "official_code_system": "kg_cbd_body", "official_code": oid,
                        "source": KG_DOTTED_SOURCE, "note": note})
            st["kg_cbd_dotted_added"] += 1
    print("KG kg_cbd dotted:", dict(st))
    return out

# ---------------------------------------------------------------------------------------------------------------
# GB places missing from the candidate list (reviewed 2026-10-17, ukie). Wikidata checked via QLever:
# Q23306 Greater London (P31 ceremonial county of England; P836 E12000007; inception 1965-04-01); ONS Code History
# Database June 2026: E12000007 "London" (E12 region, live; the GLA itself is E61000001 with parent E12000007).
# ISO 3166-2 has no code for Greater London (GB-LND is the City of London), so iso_3166_2 is empty.
GB_MANUAL = [
    {"place_id": "wd:Q23306", "country_code": "GB", "name": "Greater London", "name_native": "",
     "admin_level": "region", "parent_place_id": "wd:Q21", "iso_3166_2": "", "qid": "Q23306",
     "official_code_system": "gb_gss", "official_code": "E12000007",
     "source": "wikidata(qlever) P836 E12000007; ons_chd_june_2026 (E12 London, live)",
     "note": "London-wide local legislation (London Local Authorities Acts, TfL Acts, GLA bodies); one place, not per borough"},
]


# PL gminas / GR municipalities (reviewed 2026-10-17). Wikidata labels, P31, P131, P576 and P1366 were checked via
# QLever and wbgetentities; TERC values against pl.wikipedia infoboxes and the TERC digits inside Eurostat LAU 2024 PL
# codes (LAU[4:6] + LAU[9:13] = woj + pow + gmi). Former places carry a note starting with "former:" and their
# successors are in place_successors.csv (build_place_successors.py, MANUAL_SUCCESSORS).
PL_GMINA_REVIEWED = HERE / "proposed" / "PL_gmina_fill_reviewed.csv"
GR_DIAVGEIA = HERE / "proposed" / "GR_diavgeia_orgs.csv"
PL_GR_META = {
    "wd:Q324912": {"country_code": "PL", "name": "Wąbrzeźno", "name_native": "Wąbrzeźno", "parent_place_id": "wd:Q774738",
                   "iso_3166_2": "PL-04",
                   "note": "urban gmina (town) Wąbrzeźno, TERC 0417011 (the rural gmina 0417052 is wd:Q647959 Ryńsk)"},
    "wd:Q557603": {"country_code": "PL", "name": "Gmina Ostrowice", "name_native": "gmina Ostrowice",
                   "parent_place_id": "wd:Q1411593", "iso_3166_2": "PL-32",
                   "note": "former: rural gmina dissolved 2019-01-01 (Wikidata P576), split between gmina Drawsko "
                           "Pomorskie wd:Q558827 and gmina Złocieniec wd:Q557287 (place_successors.csv)"},
    "wd:Q12875675": {"country_code": "GR", "name": "Corfu Municipality", "name_native": "Δήμος Κέρκυρας",
                     "parent_place_id": "wd:Q842235", "iso_3166_2": "GR-F"},
    "wd:Q1737776": {"country_code": "GR", "name": "Kefalonia Municipality", "name_native": "Δήμος Κεφαλονιάς",
                    "parent_place_id": "wd:Q17320465", "iso_3166_2": "GR-F"},
    "wd:Q2520681": {"country_code": "GR", "name": "Lesbos Municipality", "name_native": "Δήμος Λέσβου",
                    "parent_place_id": "wd:Q11723838", "iso_3166_2": "GR-K"},
    "wd:Q2520687": {"country_code": "GR", "name": "Samos Municipality", "name_native": "Δήμος Σάμου",
                    "parent_place_id": "wd:Q11723844", "iso_3166_2": "GR-K"},
}


def pl_gr_rows(cand: set, have: set, problems: list) -> list:
    sys.path.insert(0, str(HERE.parent))
    import schema as S
    out = []

    def ok(pid):
        if pid in cand or pid in have or pid in {r["place_id"] for r in out}:
            return False
        if not S._PLACE_ID_RE.match(pid) or not pid.startswith("wd:Q"):
            problems.append((pid, "", "PL/GR addition: place_id is not wd:Q<n>; not added", ""))
            return False
        S.place_key(pid)
        return True
    if PL_GMINA_REVIEWED.exists():
        with PL_GMINA_REVIEWED.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                pid = (r.get("place_id") or "").strip()
                if r.get("decision") != "accept" or not ok(pid):
                    continue
                m = PL_GR_META.get(pid)
                if not m:
                    problems.append((pid, r["name"], "PL gmina not a candidate and no metadata in PL_GR_META", r["teryt"]))
                    continue
                out.append({"place_id": pid, "country_code": "PL", "name": m["name"], "name_native": m["name_native"],
                            "admin_level": "municipality", "parent_place_id": m["parent_place_id"],
                            "iso_3166_2": m["iso_3166_2"], "qid": pid[3:], "official_code_system": "pl_teryt_terc",
                            "official_code": r["teryt"],
                            "source": "codes/proposed/PL_gmina_fill_reviewed.csv; wikidata P1653/P576; "
                                      "eurostat_lau_2024 PL; pl.wikipedia TERC",
                            "note": m["note"]})
    else:
        problems.append(("", "", f"{PL_GMINA_REVIEWED} missing; no PL gminas added", ""))
    if GR_DIAVGEIA.exists():
        with GR_DIAVGEIA.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                pid = (r.get("place_id") or "").strip()
                if r.get("status") != "new" or not ok(pid):
                    continue
                m = PL_GR_META.get(pid)
                if not m:
                    problems.append((pid, r["diavgeia_label"], "GR addition without metadata in PL_GR_META", r["diavgeia_uid"]))
                    continue
                note = ""
                if r.get("dissolved_date"):
                    note = (f"former: abolished {r['dissolved_date']} (Law 4600/2019 art. 154; Wikidata P576 says 2019-01-01), "
                            f"split into {r['successor_place_ids'].replace(';', ', ')} (place_successors.csv); "
                            f"Diavgeia org {r['diavgeia_uid']} {r['diavgeia_label']}")
                out.append({"place_id": pid, "country_code": "GR", "name": m["name"], "name_native": m["name_native"],
                            "admin_level": "municipality", "parent_place_id": m["parent_place_id"],
                            "iso_3166_2": m["iso_3166_2"], "qid": pid[3:], "official_code_system": "gr_diavgeia_org",
                            "official_code": r["diavgeia_uid"],
                            "source": "codes/proposed/GR_diavgeia_orgs.csv (diavgeia.gov.gr opendata organizations); "
                                      "wikidata P31/P576/P1366",
                            "note": note})
    else:
        problems.append(("", "", f"{GR_DIAVGEIA} missing; no GR municipalities added", ""))
    return out

if __name__ == "__main__":
    main()
