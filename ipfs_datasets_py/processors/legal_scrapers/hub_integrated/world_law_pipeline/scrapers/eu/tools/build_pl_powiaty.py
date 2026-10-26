#!/usr/bin/env python3
"""Build codes/proposed/PL_powiaty.csv from GUS BDL units level 5 (codes/cache/gus_bdl_powiaty.json, official GUS data,
fetched earlier by the codes pipeline; the BDL API is quota-limited from the box) + place_additions.csv (land counties)
+ the candidate CSV (city counties = their city gmina, TERYT WWPP01x). No Wikidata SPARQL."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv
import json
from pathlib import Path

CODES = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/codes"))
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
WOJ = {"02": "DS", "04": "KP", "06": "LB", "08": "LS", "10": "LD", "12": "MP", "14": "MZ", "16": "OP", "18": "PK",
       "20": "PL", "22": "PM", "24": "SL", "26": "SK", "28": "WM", "30": "WP", "32": "ZP"}
WOJ_NAME = {"02": "dolnośląskie", "04": "kujawsko-pomorskie", "06": "lubelskie", "08": "lubuskie", "10": "łódzkie",
            "12": "małopolskie", "14": "mazowieckie", "16": "opolskie", "18": "podkarpackie", "20": "podlaskie",
            "22": "pomorskie", "24": "śląskie", "26": "świętokrzyskie", "28": "warmińsko-mazurskie",
            "30": "wielkopolskie", "32": "zachodniopomorskie"}


HIST = {"0263": "historical: Wałbrzych city county 1999-2002 (re-created 2013 as 0265); not current",
        "1431": "historical: powiat warszawski 1999-2002 (abolished; Warsaw = 1465); not current"}


def main():
    bdl = json.load((CODES / "cache" / "gus_bdl_powiaty.json").open(encoding="utf-8"))
    add = {r["official_code"]: r for r in csv.DictReader((CODES / "place_additions.csv").open(encoding="utf-8"))
           if r["country_code"] == "PL" and r["admin_level"] == "county"}
    wd = {}   # 7-digit TERYT -> qid (existing codes data, scrapers/eu/data/wd_pl_teryt.csv)
    for r in csv.DictReader((Path(__file__).resolve().parents[1] / "data" / "wd_pl_teryt.csv").open(encoding="utf-8")):
        if len(r["teryt"] or "") == 7 and not r["end"]:
            wd.setdefault(r["teryt"], r["item"].rsplit("/", 1)[-1])
    cand = {r["qid"]: r for r in csv.DictReader(CAND.open(encoding="utf-8")) if r["country_code"] == "PL"}
    out = []
    for u in sorted(bdl, key=lambda x: x["teryt"]):
        t = u["teryt"]
        city = u["kind"] == "2"
        pid, src, note = "", "", ""
        if city:
            for g in (t + "011", t + "01"):
                q = next((wd[k] for k in sorted(wd) if k.startswith(g)), None)
                if q and q in cand:
                    pid, src = cand[q]["place_id"], f"candidate gmina {cand[q]['place_name']} (TERYT {g}*)"
                    break
            note = "city county (miasto na prawach powiatu): same territory/authority as the city gmina; rada miasta acts as rada powiatu"
        elif t in add:
            pid, src = add[t]["place_id"], "place_additions.csv (county)"
        hist = t in HIST
        if hist:
            note = HIST[t]
        out.append({"teryt": t, "name": u["name"], "kind": "historical" if hist else "city_county" if city else "land_county",
                    "voivodeship": WOJ[t[:2]], "voivodeship_name": WOJ_NAME[t[:2]], "iso_3166_2": f"PL-{t[:2]}",
                    "place_id": pid, "place_id_source": src,
                    "suggested_place_key": (pid.replace(":", "_") if pid else f"plteryt_{t}"),
                    "gus_bdl_id": u["bdl_id"], "note": note})
    p = CODES / "proposed" / "PL_powiaty.csv"
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(p, len(out), "land", sum(r["kind"] == "land_county" for r in out), "city", sum(r["kind"] == "city_county" for r in out),
          "with place_id", sum(bool(r["place_id"]) for r in out))
    for r in out:
        if not r["place_id"]:
            print("  no place_id:", r["teryt"], r["name"], r["kind"])


if __name__ == "__main__":
    main()
