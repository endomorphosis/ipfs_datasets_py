#!/usr/bin/env python3
"""2026-10-30 one-off: re-map staging/eu/_unmatched/xkgzk_unmatched_*.jsonl by issuer name / muni_qid with xk_gzk.Places (32 new
wikidata/Q2989682 candidate rows + 6 town-QID aliases). Newly matched -> XK/<pk>.xkgzkremap_<ts>p<NNNN>.jsonl; still
unmatched -> _unmatched/xkgzk_unmatched_<ts>p<NNNN>.jsonl (new); doc_ids appended to _state/remap_done.txt (same
convention as remap_unmatched.py); old source files moved to _unmatched/_remapped/ (never deleted).
"""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, shutil, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
import xk_gzk as X, schema, pl_dzienniki as P  # noqa
OUT = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eu")); UNM = OUT / "_unmatched"; DONE = OUT / "_state" / "remap_done.txt"
dry = "--dry-run" in sys.argv
ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"); now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
pl = X.Places(); bym = {v[0]: v for v in pl.by.values()}
done = set(DONE.read_text().split()) if DONE.exists() else set()
files = sorted(UNM.glob("xkgzk_unmatched_*.jsonl"))
out, still, seen, invalid = defaultdict(list), [], set(), 0
for f in files:
    for ln in f.open(encoding="utf-8"):
        r = json.loads(ln); d = r["doc_id"]
        if d in seen or d in done:
            continue
        seen.add(d)
        # muni_qid was null on all 940 staged rows (old resolve() dropped it when unmatched): re-resolve the issuer name
        # with the updated matcher; fall back to muni_qid / the row's qid (= Wikidata municipality QID)
        res = pl.resolve(r.get("issuing_body_name") or "")
        hit = (bym.get(res["muni_qid"]) if res.get("muni_qid") else None) or bym.get(r.get("muni_qid") or r.get("qid") or "")
        if hit and hit[1]:
            c = hit[1]
            r.update(muni_qid=hit[0], place_id=c["place_id"], qid=c["qid"], place_name=c["place_name"], admin_level="municipality",
                     place_match="remap:muni_qid->" + hit[2], remapped_at=now, remapped_from=f.name)
            e = schema.validate_record(r)
            if e:
                invalid += 1; print("invalid", d, e[:3]); still.append(json.loads(ln)); continue
            out[c["place_id"]].append(r)
        else:
            still.append(r)
for r in still:
    e = schema.validate_record(r)
    if e: print("still-row schema issues", r["doc_id"], e[:3])
print(json.dumps({"files": len(files), "rows": len(seen), "matched": sum(map(len, out.values())), "places": len(out),
                  "still_unmatched": len(still), "invalid": invalid}))
if dry:
    sys.exit()
part, paths = 0, []
with DONE.open("a", encoding="utf-8") as df:
    for pid, rs in sorted(out.items()):
        part += 1; pk = schema.place_key(pid)
        p = OUT / "XK" / f"{pk}.xkgzkremap_{ts}p{part:04d}.jsonl"
        assert not p.exists(); P.atomic_write(p, rs, pk); paths.append(str(p))
        df.write("".join(x["doc_id"] + "\n" for x in rs))
if still:
    p = UNM / f"xkgzk_unmatched_{ts}p0001.jsonl"; assert not p.exists()
    p.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in still), encoding="utf-8"); paths.append(str(p))
(UNM / "_remapped").mkdir(exist_ok=True)
for f in files:
    shutil.move(str(f), str(UNM / "_remapped" / f.name))
print("\n".join(paths))
