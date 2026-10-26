#!/usr/bin/env python3
"""Re-resolve es_bop rows parked in _unmatched/ES with the improved resolver (spelling/typo prefixes, '(La)' articles,
Basque/Catalan/Galician hyphen/slash variants, guarded fuzzy for explicit ayuntamiento issuers). Matched rows are re-emitted
as NEW staged batches ES/<place_key>.<unmatched-batch>-reresolved.jsonl (validated, atomic); unmatched files stay in place;
_unmatched/_reemitted_es_bop.jsonl records each re-emitted doc. Mancomunidades, diputaciones, EATIM/ELA/ELM, consortia etc.
are never matched (NONMUNI_RE). Idempotent: docs already in the manifest are skipped."""
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
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from es_bop import S, Stager, OUT, UNM, STAGE  # noqa: E402
from es_places import Resolver  # noqa: E402

man = STAGE / "_unmatched" / "_reemitted_es_bop.jsonl"
done = set()
if man.exists():
    for l in open(man):
        done.add(json.loads(l)["doc_id"])
res = Resolver()
st = {"done": {}}
w = Stager("reresolve", st)
tot = still = n_new = 0
by_match = collections.Counter()
for fn in glob_jsonl(str(UNM / "*.jsonl")):
    stem = Path(fn[:-3] if fn.endswith(".gz") else fn).stem
    groups = collections.defaultdict(list)
    for l in open_text(fn):
        r = json.loads(l); tot += 1
        if r["doc_id"] in done:
            continue
        p = res.resolve(r.get("issuer_name") or "", r.get("province_code") or "")
        if not p.get("place_id"):
            still += 1; continue
        r.update(place_id=p["place_id"], qid=p.get("qid"), place_name=p.get("place_name"), admin_level=p.get("admin_level") or "municipality",
                 platform_place_id=p.get("ine"), ine_code=p.get("ine"), match=p["match"], reresolved_from=fn)
        groups[S.place_key(p["place_id"], None, "ES")].append(r)
        by_match[p["match"].split(":")[0]] += 1
    for pk, rows in groups.items():
        name = f"{pk}.{stem}-reresolved.jsonl"
        if (OUT / name).exists():
            continue
        bad = [x for x in rows if S.validate_record(x)]
        good = [x for x in rows if not S.validate_record(x)]
        if bad:
            print("quarantine-worthy", pk, len(bad)); continue
        w._write(OUT, name, good, pk)
        n_new += len(good)
        with open(man, "a") as m:
            for x in good:
                m.write(json.dumps({"doc_id": x["doc_id"], "issuer_name": x.get("issuer_name"), "place_id": x["place_id"], "place_name": x.get("place_name"),
                                    "match": x["match"], "unmatched_file": fn, "reemitted_as": str(OUT / name),
                                    "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, ensure_ascii=False) + "\n")
print(json.dumps({"unmatched_rows_scanned": tot, "already_reemitted": len(done), "reemitted_now": n_new, "still_unmatched": still, "by_match": by_match}))
