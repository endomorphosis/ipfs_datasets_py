"""Build manifests/za_overlap_crosswalk.jsonl (v2, written fresh).

Sources (all trusted, pre-dating the failed tranche worker):
- za_recon/match_detail.json  — algorithmic pairs / akn_only / exist_only
- za_recon/match_adjusted.json — manual review: 1 demotion, 3 promotions
- za_recon/existing_inventory.json — Layer 1 doc records (for promoted ids)

Reviewed ETH totals this file must reproduce (reconciliation report):
33 matched (26 HIGH + 7 MEDIUM incl. 3 manual promotions), 25 AKN-only,
12 Layer-1-only. Plus 2 explicit Layer-1 id-mapping rows:
za-bcm -> BUF, za-ekh -> EKU (mapping only; no Layer 1 id is renamed).
"""
import json
from pathlib import Path

BASE = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files"
OUT = BASE / "za_tranche1_v2" / "out" / "za_overlap_crosswalk.jsonl"
OUT.parent.mkdir(parents=True, exist_ok=True)

detail = json.load(open(BASE / "za_recon" / "match_detail.json"))
adjusted = json.load(open(BASE / "za_recon" / "match_adjusted.json"))
existing = {d["law_id"]: d for d in json.load(open(BASE / "za_recon" / "existing_inventory.json"))}

eth = detail["ETH"]
pairs = eth["pairs"]

DEMOTED_AKN = "/akn/za-eth/act/by-law/1911/public-health"
DEMOTED_EXIST_ID = "za-muni-eth-municipal-public-health-by-law-2023"

rows = []
matched_akn, matched_exist = set(), set()

for p in pairs:
    akn_uri = p["akn"]["work_uri"]
    exist_id = p["exist"]["law_id"]
    if akn_uri == DEMOTED_AKN and exist_id == DEMOTED_EXIST_ID:
        continue  # manual demotion: 112-year-apart instruments, not a match
    rows.append({
        "mdb": "ETH",
        "municipality": "eThekwini",
        "relation": "matched",
        "akn_work_uri": akn_uri,
        "akn_title": p["akn"]["title"],
        "layer1_municipality_id": p["exist"]["municipality_id"],
        "layer1_law_id": exist_id,
        "layer1_title": p["exist"]["title"],
        "confidence": p["confidence"],
        "score": p.get("score"),
        "method": p.get("method", ""),
    })
    matched_akn.add(akn_uri)
    matched_exist.add(exist_id)

# manual promotions from match_adjusted.json (strings carry both sides)
PROMOTIONS = [
    ("/akn/za-eth/act/by-law/2016/museums",
     "za-muni-eth-museums-by-law-2015"),
    ("/akn/za-eth/act/by-law/2006/surcharges-on-electricity-supplied-to-occupiers-of-municipal-property",
     "za-muni-eth-regulating-the-imposition-of-the-surcharges-on-electricity-by-law-2006"),
    ("/akn/za-eth/act/by-law/2024/problem-buildings-amendment",
     "za-muni-eth-problem-buildings-first-amendment-by-law-2023"),
]
akn_inv = {}
for line in open(BASE / "za_recon" / "akn_inventory.jsonl"):
    w = json.loads(line)
    akn_inv[w["work_uri"]] = w

for akn_uri, exist_id in PROMOTIONS:
    a = akn_inv[akn_uri]
    e = existing[exist_id]
    rows.append({
        "mdb": "ETH",
        "municipality": "eThekwini",
        "relation": "matched",
        "akn_work_uri": akn_uri,
        "akn_title": a["title"],
        "layer1_municipality_id": e["municipality_id"],
        "layer1_law_id": exist_id,
        "layer1_title": e["title"],
        "confidence": "MEDIUM",
        "score": None,
        "method": "manual-review-promoted (match_adjusted.json)",
    })
    matched_akn.add(akn_uri)
    matched_exist.add(exist_id)

# AKN-only: algorithmic akn_only minus promoted, plus demoted AKN work
akn_only = [w for w in eth["akn_only"] if w["work_uri"] not in matched_akn]
demoted_akn = akn_inv[DEMOTED_AKN]
if demoted_akn["work_uri"] not in {w["work_uri"] for w in akn_only}:
    akn_only.append(demoted_akn)
for w in akn_only:
    rows.append({
        "mdb": "ETH", "municipality": "eThekwini", "relation": "akn_only",
        "akn_work_uri": w["work_uri"], "akn_title": w["title"],
        "layer1_municipality_id": "", "layer1_law_id": "",
        "layer1_title": "", "confidence": "", "score": None, "method": "",
    })

# Layer-1-only: algorithmic exist_only minus promoted, plus demoted doc
exist_only = [d for d in eth["exist_only"] if d["law_id"] not in matched_exist]
demoted_exist = existing[DEMOTED_EXIST_ID]
if demoted_exist["law_id"] not in {d["law_id"] for d in exist_only}:
    exist_only.append(demoted_exist)
for d in exist_only:
    rows.append({
        "mdb": "ETH", "municipality": "eThekwini", "relation": "layer1_only",
        "akn_work_uri": "", "akn_title": "",
        "layer1_municipality_id": d["municipality_id"],
        "layer1_law_id": d["law_id"], "layer1_title": d["title"],
        "confidence": "", "score": None, "method": "",
    })

# explicit Layer 1 id mappings (crosswalk only; published ids unchanged)
for raw_id, mdb, name in [("za-bcm", "BUF", "Buffalo City"),
                          ("za-ekh", "EKU", "City of Ekurhuleni")]:
    rows.append({
        "mdb": mdb, "municipality": name, "relation": "layer1_id_mapping",
        "akn_work_uri": "", "akn_title": "",
        "layer1_municipality_id": raw_id, "layer1_law_id": "",
        "layer1_title": "", "confidence": "", "score": None,
        "method": "Layer 1 municipality_id is not a lowercased MDB code; "
                  f"map {raw_id} -> {mdb} when joining layers",
    })

n_matched = sum(1 for r in rows if r["relation"] == "matched")
n_akn = sum(1 for r in rows if r["relation"] == "akn_only")
n_l1 = sum(1 for r in rows if r["relation"] == "layer1_only")
print(f"matched={n_matched} akn_only={n_akn} layer1_only={n_l1} total={len(rows)}")
assert n_matched == 33, n_matched
assert n_akn == 25, n_akn
assert n_l1 == 12, n_l1
assert len(matched_akn) == 33 and len(matched_exist) == 33
with open(OUT, "w") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("wrote", OUT)
