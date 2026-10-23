#!/usr/bin/env python3
"""ES status -> _status_es.json and _blocked_es.csv."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import csv, json, collections
from pathlib import Path
STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam"))
seeds = json.load(open(Path(__file__).parent / "seeds_places.json"))
c = collections.Counter(); docs = 0; places = set(); rows = []
for s in seeds:
    p = STAGE / "_state" / "es" / f"{s['seed_id']}.json"
    st = json.loads(p.read_text()) if p.exists() else {"status": "pending"}
    c[st["status"]] += 1; docs += st.get("n_docs", 0)
    if st.get("n_docs"): places.add(s["place_id"])
    if st["status"] in ("robots_disallow", "robots_unreachable"):
        rows.append([s["seed_id"], s["host"], s["name"], s.get("ine"), s.get("place_id"), st["status"], st.get("reason", "")])
with open(STAGE / "_blocked_es.csv", "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["seed_id", "host", "name", "ine", "place_id", "reason", "detail"]); w.writerows(rows)
out = {"seeds": len(seeds), "status": dict(c), "docs": docs, "places_with_docs": len(places), "blocked_rows": len(rows)}
(STAGE / "_status_es.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out))
