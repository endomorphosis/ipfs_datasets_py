"""ES sedelectronica seeds -> INE municipality code (Wikidata P772) -> place_id in global_municipalities_candidate.csv."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, json, re, collections
cand = {r["qid"]: r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))) if r["country_code"] == "ES"}
q2ine, ine2q = collections.defaultdict(set), collections.defaultdict(set)
for r in csv.DictReader(open("wd_p772.csv")):
    q = r["item"].rsplit("/", 1)[1]; ine = r["ine"].strip()
    if re.fullmatch(r"\d{5}", ine):
        q2ine[q].add(ine); ine2q[ine].add(q)
out, st = [], collections.Counter()
for i, l in enumerate(open("seeds_ES_sede_board.jsonl")):
    s = json.loads(l)
    rec = dict(seed_id=f"es{i:04d}", host=s["host"], name=s["name"], seed_qid=s.get("qid"), ine=None, qid=None, place_id=None,
               admin_level=None, match="unmatched", seed_ok=s.get("ok"), seed_docs=len(s.get("documents") or []))
    ines = sorted(q2ine.get(s.get("qid"), []))
    if ines:
        rec["ine"] = ines[0]
        qs = [s["qid"]] + sorted(ine2q[ines[0]] - {s["qid"]})
        hit = next((q for q in qs if q in cand), None)
        if hit:
            rec.update(qid=hit, place_id=cand[hit]["place_id"], admin_level=cand[hit]["admin_level"] or "municipality", match="ine_p772")
        else:
            rec["match"] = "ine_found_not_in_candidate"
    elif s.get("qid") in cand:
        rec.update(qid=s["qid"], place_id=cand[s["qid"]]["place_id"], admin_level=cand[s["qid"]]["admin_level"], match="qid_only_no_ine")
    st[rec["match"]] += 1; out.append(rec)
json.dump(out, open("seeds_places.json", "w"), ensure_ascii=False, indent=0)
with open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam/_unmatched_es.csv"), "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["seed_id", "host", "name", "seed_qid", "ine", "match"])
    for r in out:
        if r["match"] not in ("ine_p772",): w.writerow([r["seed_id"], r["host"], r["name"], r["seed_qid"], r["ine"], r["match"]])
print(st)
