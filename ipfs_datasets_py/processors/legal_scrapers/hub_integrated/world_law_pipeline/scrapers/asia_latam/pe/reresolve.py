#!/usr/bin/env python3
"""Re-resolve PE institutions whose place was unmatched/ambiguous (resolver improved: Wikidata P36 capitals) and
re-emit their already-fetched unmatched rows as new staged batches (unmatched files are left in place;
_unmatched/_reemitted_pe.jsonl records each re-emit). Run only while pe_gobpe.py is stopped."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys as _sys; _sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/asia_latam/common")); from jsonl_io import open_text, glob_jsonl, locate  # noqa: E402,E702
import glob, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "es")); sys.path.insert(0, str(HERE.parent))
import schema as S
from pe_places import PEResolver
from pe_gobpe import write_atomic, STATE, OUT, UNM, STAGE
res = PEResolver()
man = STAGE / "_unmatched" / "_reemitted_pe.jsonl"
for sp in sorted(STATE.glob("*.json")):
    st = json.loads(sp.read_text())
    pl = st.get("place") or {}
    if pl.get("place_id") or pl.get("match") in (None, "not_municipal", "no_name") or not st.get("name"):
        continue
    new = res.resolve(st["name"], st["slug"])
    if not new.get("place_id"):
        continue
    pk = S.place_key(new["place_id"], None, "PE")
    n = 0
    for fn in glob_jsonl(str(UNM / f"{st['slug']}-p*.jsonl")):
        rows = []
        for l in open_text(fn):
            r = json.loads(l)
            r.update(place_id=new["place_id"], qid=new["qid"], place_name=new["place_name"], match=new["match"],
                     province_name=new.get("province_name"), department_name=new.get("department_name"))
            rows.append({k: v for k, v in r.items() if v is not None or k == "place_id"})
        name = f"{pk}.gobpe-{Path(fn[:-3] if fn.endswith('.gz') else fn).stem}-reresolved.jsonl"
        if (OUT / name).exists():
            continue
        write_atomic(OUT, name, rows, pk); n += len(rows)
        with open(man, "a") as m:
            m.write(json.dumps({"unmatched_file": fn, "reemitted_as": str(OUT / name), "rows": len(rows), "match": new["match"],
                                "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n")
    st["place"] = new; st["n_docs"] = st.get("n_docs", 0) + n; st["n_unmatched_reemitted"] = n
    t = sp.with_suffix(".tmp"); t.write_text(json.dumps(st, ensure_ascii=False)); os.replace(t, sp)
    print(st["slug"], new["match"], new["place_name"], "re-emitted", n)
