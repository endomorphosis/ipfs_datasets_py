#!/usr/bin/env python3
"""BM25 (+vector/graph) smoke for EE municipal IR (tip 9ef422a2a38a). Estonian bodies; diacritic-fold tokenizer
(ä/õ/ö/ü -> a/o/o/u). Gate = common Estonian municipal-law terms; all must rank. Vector + graph checked as extras."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, sys
from pathlib import Path
os.environ.setdefault("HF_HOME", "/workspace/country-laws-ir/cache/hf")
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"; os.environ.setdefault("HF_HUB_OFFLINE", "1")
sys.path.insert(0, "/workspace/country-laws-ir")
from country_laws_ir.query import Release

TS = "9ef422a2a38a"
ROOT = Path("/workspace/country-laws-ir/releases/ipfs_estonia_municipal_laws_ir")
OUT = Path(f"/workspace/country-laws-ir/reports/estonia_municipal_bm25_smoke_{TS}.json")
QUERIES = ["määrus", "volikogu", "vallavalitsus", "linnavalitsus", "eelarve", "toetus", "kord", "jäätmehoolduseeskiri",
           "parkimine", "sotsiaalhoolekanne", "huvihariduse", "kehtestamine", "rakendussätted", "Narva", "Tallinn"]
GATE = ["määrus", "volikogu", "vallavalitsus", "linnavalitsus", "eelarve", "toetus", "kord", "kehtestamine", "rakendussätted"]

def main() -> int:
    rel = Release(ROOT)
    d = {"tip": TS, "queries": {}, "ranked": [], "empty": []}
    for q in QUERIES:
        hits = rel.bm25(q, top_k=5)
        d["queries"][q] = {"n": len(hits), "top": [{"score": h.get("score"), "title": (h.get("title") or "")[:120],
                           "instrument_id": h.get("instrument_id"), "entry_cid": h.get("entry_cid")} for h in hits[:3]]}
        (d["ranked"] if hits else d["empty"]).append(q)
    d["bm25_pass"] = all(q in d["ranked"] for q in GATE); d["gate"] = GATE
    vq = "jäätmete kogumine ja vedu"
    vh = rel.vector(vq, top_k=5)
    d["vector"] = {"query": vq, "n": len(vh), "top": [{"score": h.get("score"), "title": (h.get("title") or "")[:120]} for h in vh[:3]]}
    seed = d["queries"]["eelarve"]["top"][0]["entry_cid"] if d["queries"]["eelarve"]["top"] else None
    nb = rel.neighbors(seed, limit=10) if seed else []
    d["graph"] = {"seed": seed, "n": len(nb), "sample": [{k: n.get(k) for k in ("edge_type", "target_cid", "source_cid", "score") if k in n} for n in nb[:3]]}
    d["vector_pass"] = len(vh) > 0; d["graph_pass"] = len(nb) > 0
    d["pass"] = d["bm25_pass"] and d["vector_pass"] and d["graph_pass"]
    OUT.write_text(json.dumps(d, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: d[k] for k in ("pass", "bm25_pass", "vector_pass", "graph_pass", "ranked", "empty")}, ensure_ascii=False, indent=1))
    print(json.dumps({"vector": d["vector"], "graph": d["graph"]}, ensure_ascii=False, indent=1, default=str))
    return 0 if d["pass"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
