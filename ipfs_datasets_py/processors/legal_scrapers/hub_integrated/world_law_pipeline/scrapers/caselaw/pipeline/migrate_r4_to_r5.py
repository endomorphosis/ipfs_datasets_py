"""One-off: move live r4 shards (+manifest/summary/unmatched) of a source to out/<src>/superseded/r4/ (NOT deleted) and rewrite the same rows as r5.
usage: migrate_r4_to_r5.py cjeu_cellar|nl_rechtspraak. No refetch. r5 data change: terms.pending_legal_review=true rows => restricted_ai_training=TRUE (CJEU)."""
import sys, os, glob, json, shutil
import pyarrow.parquet as pq
import caselaw_schema as cs
from cl_common import *
SRC = sys.argv[1]; base = f"{OUT}/{SRC}"; sup = f"{base}/superseded/r4"
assert SRC in ("cjeu_cellar", "nl_rechtspraak")
assert not os.path.exists(sup), "already migrated"
os.makedirs(sup)
olds = {k: sorted(glob.glob(f"{base}/{k}/part-*.parquet")) for k in ("decision", "opinion")}
for f in ("manifest.jsonl", "summary.json", "unmatched_courts.json", "rejected_rows.jsonl"):
    if os.path.exists(f"{base}/{f}"): shutil.move(f"{base}/{f}", f"{sup}/{f}")
for k, ps in olds.items():
    os.makedirs(f"{sup}/{k}", exist_ok=True)
    for p in ps: shutil.move(p, f"{sup}/{k}/{os.path.basename(p)}")
open(f"{sup}/SUPERSEDED.md", "w").write("Superseded 2026-10-29 by caselaw-raw/v0-r5 (schema_caselaw_v3.md). r4 shards kept for audit; content migrated 1:1 (no refetch): "
    "kv schema_doc_version r5; rows with terms.pending_legal_review=true now restricted_ai_training=true; summary/unmatched regenerated from the data.\n")
n = {"decision": 0, "opinion": 0}; changed = 0
for kind in ("decision", "opinion"):
    for i, p in enumerate(sorted(glob.glob(f"{sup}/{kind}/part-*.parquet"))):
        rows = pq.read_table(p).to_pylist()
        for r in rows:
            m = json.loads(r["metadata_json"])
            if (m.get("terms") or {}).get("pending_legal_review") is True and r["restricted_ai_training"] is not True:
                r["restricted_ai_training"] = True; changed += 1
        t = cs.cast_rows(rows, kind)
        os.makedirs(f"{base}/{kind}", exist_ok=True)
        final = f"{base}/{kind}/part-{i:04d}.parquet"; tmp = final.replace("part-", ".part-") + ".writing"
        size = cs.write_shard(t, tmp, kind); os.replace(tmp, final); n[kind] += t.num_rows
        with open(f"{base}/manifest.jsonl", "a") as f:
            f.write(json.dumps({"time_la": now_la(), "path": final, "record_type": kind, "rows": t.num_rows, "bytes": size, "migrated_from": "r4", **preflight("migrate")}) + "\n")
        print(final, t.num_rows, size, flush=True)
old = json.load(open(f"{sup}/summary.json"))
keep = {k: old[k] for k in ("fails", "n_fails", "http_requests") if k in old}
s = write_summary(SRC, migrated_from="r4", migrated_la=now_la(), flags_changed_to_restricted=changed, previous_r4_summary={k: v for k, v in old.items() if k not in keep}, **keep)
print(dump_unmatched(SRC, None)); print(json.dumps({k: s[k] for k in ("decisions_total_incl_resume", "rows_total", "shards_total", "bytes_total", "court_match")}), "changed", changed)
