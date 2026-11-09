"""One-off: move CJEU r3 shards to out/cjeu_cellar/superseded/r3/ (not deleted) and rewrite them as r4 (same rows, same shard layout, no refetch)."""
import sys, os, glob, json, shutil, time
import pyarrow.parquet as pq
import caselaw_schema as cs
from cl_common import *
import job1_cjeu as J
SRC = "cjeu_cellar"; base = f"{OUT}/{SRC}"; sup = f"{base}/superseded/r3"
assert not os.path.exists(sup), "already migrated"
os.makedirs(sup)
olds = {k: sorted(glob.glob(f"{base}/{k}/part-*.parquet")) for k in ("decision", "opinion")}
for f in ("manifest.jsonl", "summary.json", "unmatched_courts.json"):
    if os.path.exists(f"{base}/{f}"): shutil.move(f"{base}/{f}", f"{sup}/{f}")
for k, ps in olds.items():
    os.makedirs(f"{sup}/{k}", exist_ok=True)
    for p in ps: shutil.move(p, f"{sup}/{k}/{os.path.basename(p)}")
open(f"{sup}/SUPERSEDED.md", "w").write("Superseded 2026-10-29 by caselaw-raw/v0-r4 (schema_caselaw_v2.md). r3 shards kept for audit; content migrated 1:1 (no refetch): "
    "court_name_raw aligned with matcher input, licence_class open->unknown, terms.pending_legal_review added, celex moved to extras, kv schema_doc_version r4.\n")
tot = {"decision": 0, "opinion": 0}; nbytes = {"decision": 0, "opinion": 0}; shards = {"decision": 0, "opinion": 0}
for kind in ("decision", "opinion"):
    for p in sorted(glob.glob(f"{sup}/{kind}/part-*.parquet")):
        rows = pq.read_table(p).to_pylist()
        for r in rows:
            m = json.loads(r["metadata_json"])
            ex = m.setdefault("extras", {})
            if "celex" in m: ex["celex"] = m.pop("celex")
            m["terms"] = J.TERMS
            r["metadata_json"] = m
            r["licence_class"] = "unknown"; r["licence"] = J.LICENCE
            if kind == "decision":
                letter = r["docket_number"][0]; nm = J.COURT[letter]
                r["court_name_raw"] = nm
                assert r["court_key_provisional"] == cs.provisional_key("EU", None, __import__("court_matcher").norm_name(nm), SRC, letter), "provisional key drifted"
        t = cs.cast_rows(rows, kind)
        os.makedirs(f"{base}/{kind}", exist_ok=True)
        final = f"{base}/{kind}/part-{shards[kind]:04d}.parquet"; tmp = final.replace("part-", ".part-") + ".writing"
        size = cs.write_shard(t, tmp, kind); os.replace(tmp, final)
        shards[kind] += 1; tot[kind] += t.num_rows; nbytes[kind] += size
        with open(f"{base}/manifest.jsonl", "a") as f:
            f.write(json.dumps({"time_la": now_la(), "path": final, "record_type": kind, "rows": t.num_rows, "bytes": size, "migrated_from": "r3", **preflight("migrate")}) + "\n")
        print(final, t.num_rows, size, flush=True)
old = json.load(open(f"{sup}/summary.json"))
old.update(decisions_total_incl_resume=tot["decision"], migrated_from="r3", migrated_la=now_la(), schema_doc_version=cs.SCHEMA_DOC_VERSION,
           shards_total=shards, bytes_total=nbytes, rows_total=tot)
json.dump(old, open(f"{base}/summary.json", "w"), indent=1)
print(dump_unmatched(SRC, None))
