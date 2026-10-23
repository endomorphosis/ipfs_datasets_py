"""Wikidata ko/zh/en labels + P131 for KR/TW/NZ candidate places -> staging/eap/_eap_work/wd_kr_tw_nz.json"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, json, requests, time
W = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eap/_eap_work")
S = requests.Session(); S.headers["User-Agent"] = "world-law-research-bot/1.0 (eap lane; research)"
def get(ids):
    for a in range(8):
        try: return S.get("https://www.wikidata.org/w/api.php", params=dict(action="wbgetentities", ids="|".join(ids), props="labels|aliases|claims",
                          languages="ko|zh-tw|zh|zh-hant|en|mi", format="json"), timeout=60).json()
        except Exception as e: print("retry", e, flush=True); time.sleep(15 * (a + 1))
    return {"entities": {}}
out = {}
for cc in ["KR", "TW", "NZ"]:
    rows = {x["qid"]: x for x in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))) if x["country_code"] == cc}
    q = list(rows)
    for i in range(0, len(q), 25):
        for k, e in get(q[i:i + 25]).get("entities", {}).items():
            if k not in rows: continue
            labs = [v["value"] for v in e.get("labels", {}).values()] + [a["value"] for v in e.get("aliases", {}).values() for a in v]
            p131 = [c["mainsnak"]["datavalue"]["value"]["id"] for c in e.get("claims", {}).get("P131", []) if c["mainsnak"].get("datavalue")]
            row = rows[k]; out[k] = {"cc": cc, "labels": labs, "p131": p131, "place_name": row["place_name"], "admin_level": row["admin_level"],
                                     "state_code": row["state_code"], "iso": row["iso_3166_2"], "place_id": row["place_id"], "source_url": row["source_url"]}
        time.sleep(3)
    print(cc, len(rows), flush=True)
json.dump(out, open(f"{W}/wd_kr_tw_nz.json.tmp", "w"), ensure_ascii=False)
import os; os.rename(f"{W}/wd_kr_tw_nz.json.tmp", f"{W}/wd_kr_tw_nz.json"); print("done", len(out))
