"""validate_out.py <source> [<source> ...]: shards (all 4 kinds), cross-table, cross-source ids, tombstones, manifest, summary, unmatched_courts.json."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys, glob, json, os
import pyarrow.parquet as pq
import caselaw_schema as cs

OUT = (str(_LEGAL_WS) + "/case_law/out")
def check(src):
    base = f"{OUT}/{src}"; P = []; rows = {k: 0 for k in cs.RECORD_TYPES}; paths = {k: [] for k in cs.RECORD_TYPES}
    for kind in cs.RECORD_TYPES:
        for p in sorted(glob.glob(f"{base}/{kind}/part-*.parquet")):
            t = pq.read_table(p); pr = cs.validate_caselaw_table(t, kind)
            P += [f"{p}: {x}" for x in pr]; rows[kind] += t.num_rows; paths[kind].append(p)
            print(f"{p} rows={t.num_rows} problems={len(pr)}")
    allp = [p for k in cs.RECORD_TYPES for p in paths[k]]
    P += cs.validate_id_uniqueness(allp)
    P += cs.validate_cross(paths["decision"], paths["opinion"])
    tp = f"{base}/tombstones.jsonl"
    if os.path.exists(tp): P += cs.validate_tombstones_file(tp)
    # stray temp/partial shard files
    for kind in cs.RECORD_TYPES:
        for p in glob.glob(f"{base}/{kind}/.part-*") + glob.glob(f"{base}/{kind}/*.writing"): P.append(f"stray partial file {p}")
    # manifest: every live shard listed EXACTLY once with matching rows/bytes/record_type; no stale entries
    mf = f"{base}/manifest.jsonl"; listed = {}; dup = 0
    if not os.path.exists(mf): P.append("manifest.jsonl missing")
    else:
        for i, line in enumerate(open(mf), 1):
            if not line.strip(): continue
            r = json.loads(line)
            if r["path"] in listed: dup += 1
            listed[r["path"]] = r
        if dup: P.append(f"manifest: {dup} duplicate path entries")
        for kind in cs.RECORD_TYPES:
            for p in paths[kind]:
                r = listed.get(p)
                if not r: P.append(f"manifest: shard not listed {p}"); continue
                if r["rows"] != pq.ParquetFile(p).metadata.num_rows: P.append(f"manifest: rows mismatch {p}")
                if r["bytes"] != os.path.getsize(p): P.append(f"manifest: bytes mismatch {p}")
                if r.get("record_type") != kind: P.append(f"manifest: record_type {r.get('record_type')} != directory {kind} for {p}")
        for p in listed:
            if not os.path.exists(p): P.append(f"manifest: lists missing file {p}")
    nbytes = {k: sum(os.path.getsize(p) for p in paths[k]) for k in cs.RECORD_TYPES}
    # decision-side court match counts straight from the data
    cm = {"matched": 0, "ambiguous": 0, "unmatched": 0}; exp = {}
    for p in paths["decision"]:
        t = pq.read_table(p, columns=["court_name_raw", "court_match_status", "court_key_provisional", "country_iso", "admin1"])
        for nm, st, pk, iso, a1 in zip(*(t.column(n).to_pylist() for n in t.column_names)):
            cm[st] = cm.get(st, 0) + 1
            if st != "matched":
                e = exp.setdefault((iso, a1, nm or "", st), {"rows": 0, "keys": set()}); e["rows"] += 1; e["keys"].add(pk)
    # summary.json: every total derived from the shards on disk
    sf = f"{base}/summary.json"
    if not os.path.exists(sf): P.append("summary.json missing")
    else:
        s = json.load(open(sf))
        rj = f"{base}/rejected_rows.jsonl"; nrej = sum(1 for _ in open(rj)) if os.path.exists(rj) else 0
        checks = {"decisions_total_incl_resume": rows["decision"], "rows_total": rows, "shards_total": {k: len(paths[k]) for k in cs.RECORD_TYPES},
                  "bytes_total": nbytes, "court_match": cm, "n_rejected_rows": nrej, "schema_doc_version": cs.SCHEMA_DOC_VERSION}
        for k, v in checks.items():
            if s.get(k) != v: P.append(f"summary: {k} = {s.get(k)} != data {v}")
        if not isinstance(s.get("n_fails"), int) or not isinstance(s.get("fails"), list) or s["n_fails"] < len(s["fails"]): P.append("summary: n_fails/fails inconsistent")
        if rows["decision"] != rows["opinion"]: P.append(f"decision rows {rows['decision']} != opinion rows {rows['opinion']} (1:1 sources)")
    # unmatched_courts.json vs decision shards: full content check (country, admin1, name, status, rows, provisional keys)
    uf = f"{base}/unmatched_courts.json"
    if not os.path.exists(uf): P.append("unmatched_courts.json missing")
    else:
        u = json.load(open(uf))
        got = {(i["country_iso"], i["admin1"], i["court_name_raw"] or "", i["status"]): i for i in u.get("unmatched", [])}
        if len(got) != len(u.get("unmatched", [])): P.append("unmatched: duplicate court entries")
        if u.get("courts_dataset_revision") != cs.COURTS_DATASET_REVISION: P.append("unmatched: courts_dataset_revision")
        if u.get("schema_doc_version") != cs.SCHEMA_DOC_VERSION: P.append("unmatched: schema_doc_version")
        if "match_stats_this_run" not in u: P.append("unmatched: match_stats_this_run key missing")
        for i in u.get("unmatched", []):
            a1 = i.get("admin1")
            if a1 is not None and not cs.RE_ADMIN1.match(a1): P.append(f"unmatched: admin1 {a1!r} malformed")
            if i.get("status") not in ("unmatched", "ambiguous"): P.append(f"unmatched: status {i.get('status')!r}")
        if set(got) != set(exp): P.append(f"unmatched: court set differs (missing {sorted(set(exp)-set(got), key=str)[:3]}, extra {sorted(set(got)-set(exp), key=str)[:3]})")
        for k in set(got) & set(exp):
            if got[k]["rows"] != exp[k]["rows"] or sorted(got[k].get("provisional_keys", [])) != sorted(exp[k]["keys"]): P.append(f"unmatched: rows/provisional keys differ for {k}")
    print(src, "rows", rows)
    return P, allp

if __name__ == "__main__":
    allP = []; allpaths = []
    for src in sys.argv[1:]:
        P, ap = check(src); allP += [f"{src}: {x}" for x in P]; allpaths += ap
    if len(sys.argv) > 2: allP += [f"cross-source: {x}" for x in cs.validate_id_uniqueness(allpaths)]
    print("PROBLEMS:", allP[:15] if allP else "none")
    sys.exit(1 if allP else 0)
