#!/usr/bin/env python3
"""Re-map lexml rows parked in _unmatched/BR with the IBGE-official-name mapping (shared crosswalk br_ibge) + rename aliases.
Matched rows are re-emitted as NEW staged batches BR/<place_key>.<unmatched-stem>-reresolved.jsonl (validated, atomic, never
overwritten); unmatched files stay in place; _unmatched/_reemitted_br.jsonl records each re-emitted doc. Idempotent."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys as _sys; _sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/asia_latam/common")); from jsonl_io import open_text, glob_jsonl, locate  # noqa: E402,E702
import glob, json, os, sys, collections
from datetime import datetime, timezone
from pathlib import Path
import lexml as L
S, OUT, UNM, STAGE = L.S, L.OUT, L.UNM, L.STAGE
man = STAGE / "_unmatched" / "_reemitted_br.jsonl"
done = {json.loads(l)["doc_id"] for l in open(man)} if man.exists() else set()
wd = L.load_wd()
tot = still = new = 0
for fn in glob_jsonl(str(UNM / "*.jsonl")):
    stem = Path(fn[:-3] if fn.endswith(".gz") else fn).stem; groups = collections.defaultdict(list)
    for l in open_text(fn):
        r = json.loads(l); tot += 1
        if r["doc_id"] in done:
            continue
        loc = r.get("platform_place_id") or ";".join(r["lexml_urn"].split(":")[2].split(";")[1:])
        p = L.place_for(loc, wd)
        if not p:
            still += 1; continue
        r.update(p); r["reresolved_from"] = fn
        groups[S.place_key(p["place_id"], None, "BR")].append(r)
    for pk, rows in groups.items():
        fin = OUT / f"{pk}.{stem}-reresolved.jsonl"
        if fin.exists():
            continue
        if any(S.validate_record(x) for x in rows):
            print("invalid rows, skipped", pk); continue
        tmp = OUT / f".{fin.stem}.tmp.jsonl"
        with tmp.open("w") as fh:
            for x in rows:
                fh.write(json.dumps(x, ensure_ascii=False) + "\n")
            fh.flush(); os.fsync(fh.fileno())
        v = S.validate_file(tmp, expect_place_key=pk)
        if not v["ok"]:
            os.unlink(tmp); print("validate_file failed", pk, v["errors"][:2]); continue
        os.rename(tmp, fin); new += len(rows)
        with open(man, "a") as m:
            for x in rows:
                m.write(json.dumps({"doc_id": x["doc_id"], "place_id": x["place_id"], "place_name": x.get("place_name"), "unmatched_file": fn,
                                    "reemitted_as": str(fin), "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, ensure_ascii=False) + "\n")
print(json.dumps({"unmatched_rows_scanned": tot, "already_reemitted": len(done), "reemitted_now": new, "still_unmatched": still}))
