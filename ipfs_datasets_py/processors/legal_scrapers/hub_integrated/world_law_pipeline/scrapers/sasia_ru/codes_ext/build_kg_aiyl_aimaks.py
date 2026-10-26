#!/usr/bin/env python3
"""KG aiyl aimaks (codes/proposed/KG_aiyl_aimaks.csv, 592 rows from the CBD (cbd.minjust.gov.kg) issuing-body list)
-> place_id per CBD issuing body.

Resolution (place_id must satisfy schema._PLACE_ID_RE = gnis:N | wd:QN | iso:..; there is no non-Wikidata
place_id convention for municipalities, so bodies without a QID are NOT given an invented id):
  1. wikidata_id from the proposed file (wd_candidates == 1)
  2. otherwise a unique ru/ky label-stem match against the KG places of global_municipalities_candidate.csv
     (labels/P131 from QLever, cached in pipeline/codes/cache/wd_kg_candidates_labels.tsv), disambiguated by the
     parent district when the stem is shared.
Outputs (codes_ext/):
  kg_body_to_place.csv        one row per resolved body (plus merged_from_body_ids aliases): cbd_issuing_body_id, place_id, ...
  kg_body_ambiguous.csv       bodies whose name matches several places (or wd_candidates > 1), left out above
  kg_body_unresolved.csv      bodies with no QID (no valid place_id possible without a new id convention)
  kg_aiyl_aimaks_flags.csv    every body with its flags (duplicate place, near-duplicate / placeholder body id, ...)
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import collections, csv, re, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "codes" / "proposed" / "KG_aiyl_aimaks.csv"
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
WD = HERE.parent / "pipeline" / "codes" / "cache" / "wd_kg_candidates_labels.tsv"

def lit(s):
    s = s.strip()
    m = re.match(r'^"(.*)"(@\w+)?$', s, re.S)
    return m.group(1) if m else s

SUFFIX = r"(айыл(ный|дык)?\s+(аймак|аймагы|округ)|аильный\s+округ|ayil\s+okrug|aiyl\s+aimak)"
def stem(s):
    s = (s or "").lower().replace("ё", "е").replace("ө", "о").replace("ү", "у").replace("ң", "н")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(SUFFIX, " ", s)
    s = re.sub(r"[^a-zа-я0-9]+", "", s)
    # ru adjective endings -> noun-ish stem (Ленинпольский / Ленинполь, Теплоключенский / Теплоключенка)
    s = re.sub(r"(ск(ий|ого|ая)|инский|енский|овский)$", "", s)
    return re.sub(r"(ка|ое|ий|ый|а|о|ы|и)$", "", s)

def dist(s):
    # district key: first 5 letters of the stem (Ат-Башинский район / Ат-Башынского / Ат-Башы району -> атбаш)
    return stem(re.sub(r"(районунун|району|район(а|у)?|ского|ского)", "", (s or "").lower()))[:5]

def main():
    cand = {r["qid"]: r for r in csv.DictReader(CAND.open(encoding="utf-8"))
            if r["country_code"] == "KG" and r["qid"] and r["admin_level"] == "municipality"}
    wd = {}
    for line in WD.read_text(encoding="utf-8").splitlines()[1:]:
        f = (line.split("\t") + [""] * 5)[:5]
        q = f[0].rsplit("/", 1)[-1].rstrip(">")
        if q in cand:
            par = lit(f[3])
            paren = re.findall(r"\((.*?)\)", lit(f[1]) + " " + lit(f[2]))
            wd[q] = {"ru": lit(f[1]), "ky": lit(f[2]), "dists": {dist(x) for x in par.split("|") + paren if x}}
    idx = collections.defaultdict(set)
    for q, r in cand.items():
        for nm in (wd.get(q, {}).get("ru"), wd.get(q, {}).get("ky"), r["place_name"]):
            if nm and stem(nm):
                idx[stem(nm)].add(q)
    src = list(csv.DictReader(SRC.open(encoding="utf-8")))
    # districts each name stem occurs in within the proposed file (Ак-Жар exists in Ат-Башы AND Узген, ...)
    stem_dists = collections.defaultdict(set)
    for r in src:
        if r["parent_district_ru"].strip():
            stem_dists[stem(r["aiyl_aimak_ru"])].add(dist(r["parent_district_ru"]))
    ids = [r["cbd_issuing_body_id"].strip() for r in src]
    idset = set(ids)
    out, amb, unres, flags = [], [], [], []
    for r, bid in zip(src, ids):
        fl, q, how = [], "", ""
        name = r["aiyl_aimak_ru"].strip()
        parent = r["parent_district_ru"].strip()
        if not bid:
            fl.append("missing_body_id")
        elif not re.fullmatch(r"[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9.]+", bid):
            fl.append("nonstandard_body_id")
        for other in idset:
            # Skip empty/missing ids: every short bid would otherwise match startswith('') with len<=2.
            if other and bid and other != bid and bid.startswith(other) and len(bid) - len(other) <= 2:
                fl.append(f"near_duplicate_body_id_of:{other}")
        if r["wikidata_id"].strip() and r["wd_candidates"].strip() == "1":
            q, how = r["wikidata_id"].strip(), "proposed_wikidata_id"
        elif r["wd_candidates"].strip() not in ("", "0", "1"):
            fl.append(f"ambiguous:wd_candidates={r['wd_candidates']}")
        else:
            hits = set()
            for nm in (name, r["aiyl_aimak_ky"]):
                if nm and stem(nm):
                    hits |= idx.get(stem(nm), set())
            if len(hits) > 1 and parent:
                hits2 = {h for h in hits if dist(parent) in wd.get(h, {}).get("dists", set())}
                hits = hits2 or hits
            if len(hits) == 1:
                q = hits.pop()
                d = wd.get(q, {}).get("dists", set())
                sd = stem_dists.get(stem(name), set())
                if parent and d and dist(parent) not in d:
                    fl.append(f"name_match_district_differs:{q}")
                    q = ""
                elif not d and len(sd) > 1:
                    # Wikidata item has no P131 and the name occurs in several districts: cannot tell which one
                    fl.append(f"ambiguous:name_in_{len(sd)}_districts_wd_item_without_P131:{q}")
                    q = ""
                else:
                    how = "candidate_name_match" + ("+district" if d else "")
            elif len(hits) > 1:
                fl.append("ambiguous:name_matches:" + "|".join(sorted(hits)))
        if r["region_note"].strip():
            fl.append("region_" + r["region_note"].strip())
        merged = [m.strip() for m in re.split(r"[|;,]", r.get("merged_from_body_ids") or "") if m.strip()]
        rec = {"cbd_issuing_body_id": bid, "place_id": f"wd:{q}" if q else "", "place_key": f"wd_{q}" if q else "",
               "name": name, "parent": parent, "region_code": r["region_code"].strip(),
               "cbd_issuing_body_name": r["cbd_issuing_body_name"].strip(), "match": how, "flags": ";".join(fl),
               "_merged": merged}
        flags.append(rec)
    by_place = collections.Counter(x["place_id"] for x in flags if x["place_id"] and x["cbd_issuing_body_id"])
    seen = set()
    for x in flags:
        if x["place_id"] and by_place[x["place_id"]] > 1:
            x["flags"] = ";".join(filter(None, [x["flags"], f"duplicate_place:{by_place[x['place_id']]}_bodies"]))
        if not x["cbd_issuing_body_id"]:
            continue
        if x["cbd_issuing_body_id"] in seen:
            x["flags"] += ";duplicate_body_id"
            continue
        seen.add(x["cbd_issuing_body_id"])
        pub = {k: v for k, v in x.items() if not k.startswith("_")}
        if "ambiguous:" in x["flags"]:
            amb.append(pub)
        elif x["place_id"]:
            out.append(pub)
            for mid in x.get("_merged") or []:
                if not mid or mid in seen:
                    continue
                seen.add(mid)
                y = dict(pub)
                y["cbd_issuing_body_id"] = mid
                out.append(y)
        else:
            unres.append(pub)
    # flags file: one row per source body (no _merged helper field)
    flags_pub = [{k: v for k, v in x.items() if not k.startswith("_")} for x in flags]
    cols = [c for c in flags[0] if not c.startswith("_")]
    for fn, rows in (("kg_body_to_place.csv", out), ("kg_body_ambiguous.csv", amb),
                     ("kg_body_unresolved.csv", unres), ("kg_aiyl_aimaks_flags.csv", flags_pub)):
        tmp = HERE / (fn + ".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        tmp.replace(HERE / fn)
    c = collections.Counter(x["match"] for x in out)
    print(f"bodies={len(src)} resolved={len(out)} {dict(c)} distinct_places={len({x['place_id'] for x in out})} "
          f"ambiguous={len(amb)} unresolved={len(unres)} missing_id={sum(not i for i in ids)}")
    fc = collections.Counter(f.split(":")[0] for x in flags_pub for f in x["flags"].split(";") if f)
    print("flags:", dict(fc))

if __name__ == "__main__":
    main()
