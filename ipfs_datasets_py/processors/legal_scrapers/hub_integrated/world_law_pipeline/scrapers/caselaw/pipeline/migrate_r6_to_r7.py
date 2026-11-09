"""One-off: move live r6 shards (+manifest/summary/unmatched; rejected_rows.jsonl is COPIED) of a source to out/<src>/superseded/r6/ (NOTHING deleted) and rewrite the same rows as r7.
usage: migrate_r6_to_r7.py <source> [--dry]. Local data only; no fetching. r7 row changes (r6_rules.apply_r7):
  CH : the 20 _nodate rows: year from the docket when unambiguous else decision_date/year NULL (+ source_default flag); BGE/ATF full date recovered from the heading; 12-31 placeholders -> year precision;
       TG navigation boilerplate stripped (rehash); body_type recomputed (collection before court, supervisory bodies, exact series names, CEDH exempt); 2 ZH UVEK guideline rows flagged not_decision
  all: e-mail redaction with the r7 regex (non-ASCII, full-width at, spaced ' @ ') + rehash; body_type recomputed (non-CH sources are all court)"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import sys, os, glob, json, shutil, re, collections
import pyarrow.parquet as pq
import caselaw_schema as cs
import r6_rules
from cl_common import *
SRC = sys.argv[1]; DRY = "--dry" in sys.argv
assert SRC in ("cjeu_cellar", "nl_rechtspraak", "ch_entscheidsuche", "br_stj_dados_abertos")
base = f"{OUT}/{SRC}"; sup = f"{base}/superseded/r6"
print(now_la(), "start", SRC, "dry" if DRY else "LIVE", preflight("migrate r7 start"), flush=True)
if not DRY:
    assert not os.path.exists(sup), "already migrated"
    os.makedirs(sup)
    for f in ("manifest.jsonl", "summary.json", "unmatched_courts.json"):
        if os.path.exists(f"{base}/{f}"): shutil.move(f"{base}/{f}", f"{sup}/{f}")
    if os.path.exists(f"{base}/rejected_rows.jsonl"): shutil.copy2(f"{base}/rejected_rows.jsonl", f"{sup}/rejected_rows.jsonl")
    for k in cs.RECORD_TYPES:
        ps = sorted(glob.glob(f"{base}/{k}/part-*.parquet"))
        if ps: os.makedirs(f"{sup}/{k}", exist_ok=True)
        for p in ps: shutil.move(p, f"{sup}/{k}/{os.path.basename(p)}")
    open(f"{sup}/SUPERSEDED.md", "w").write("Superseded 2026-10-29 by caselaw-raw/v0-r7 (schema_caselaw_v5.md). r6 shards kept for audit; rows rewritten from these shards (no refetch). "
        "r7 row changes: CH _nodate dates (docket year or NULL), BGE/ATF full dates recovered from headings, 12-31 placeholders -> year precision, TG navigation boilerplate stripped (rehash), "
        "body_type recomputed (collection before court, CEDH exempt from Swiss rules), 2 ZH guideline rows flagged not_decision, e-mail regex v2 (non-ASCII / spaced at) re-redaction + rehash. "
        "summary/unmatched regenerated from the data. rejected_rows.jsonl was copied (the live file stays).\n")
src_dir = (lambda k: f"{sup}/{k}") if not DRY else (lambda k: f"{base}/{k}")
st = collections.Counter(); lists = collections.defaultdict(list); n = {"decision": 0, "opinion": 0}
decp = sorted(glob.glob(f"{src_dir('decision')}/part-*.parquet")); opp = sorted(glob.glob(f"{src_dir('opinion')}/part-*.parquet"))
assert len(decp) == len(opp) and decp, (len(decp), len(opp))
for i, (dp, op_) in enumerate(zip(decp, opp)):
    drows = pq.read_table(dp).to_pylist(); orows = {r["decision_id"]: r for r in pq.read_table(op_).to_pylist()}
    assert len(orows) == len(drows) and {r["id"] for r in drows} == set(orows), f"shard {i}: decision/opinion pairing differs"
    new_d, new_o = [], []
    for d in drows:
        o = orows[d["id"]]; before_bt = d.get("body_type"); before_h = o["text_sha256"]
        s = r6_rules.apply_r7(d, o); ch = []
        if s["tg_strip"]: ch.append("tg_nav_stripped"); st["tg_stripped"] += 1; lists["tg_stripped"].append(d["id"])
        if s["date"]: ch.append("date_" + s["date"]); st["date_" + s["date"]] += 1; lists["date_" + s["date"]].append((d["source_record_id"], d["decision_date"]))
        if s["emails"]: ch.append("emails"); st["emails_redacted"] += s["emails"]; st["email_rows"] += 1
        if s["not_decision"]: ch.append("not_decision"); st["not_decision"] += 1; lists["not_decision"].append(d["id"])
        if d.get("body_type") != before_bt: ch.append("body_type"); st["body_type_changed"] += 1; lists["body_type_changes"].append((before_bt, d.get("body_type")))
        if s["labels"]: ch.append("labels")
        st["body_type__" + str(d.get("body_type"))] += 1
        if ch:
            for r_ in (d, o): r6_rules._meta(r_)["r7_migration"] = {"from": "r6", "changes": sorted(set(ch))}
        new_d.append(d); new_o.append(o)
    for kind, rows in (("decision", new_d), ("opinion", new_o)):
        t = cs.cast_rows(rows, kind)
        final = f"{base}/{kind}/part-{i:04d}.parquet"; tmp = f"{base}/{kind}/.part-{i:04d}.parquet.writing"
        if DRY:
            pr = cs.validate_caselaw_table(t, kind); assert not pr, pr; n[kind] += t.num_rows; continue
        os.makedirs(f"{base}/{kind}", exist_ok=True)
        size = cs.write_shard(t, tmp, kind); os.replace(tmp, final); n[kind] += t.num_rows
        with open(f"{base}/manifest.jsonl", "a") as f:
            f.write(json.dumps({"time_la": now_la(), "path": final, "record_type": kind, "rows": t.num_rows, "bytes": size, "migrated_from": "r6", **preflight("migrate r7")}) + "\n")
        print(final, t.num_rows, size, flush=True)
for k_, v in lists.items(): st["list_" + k_] = len(v)
print(now_la(), "rows", n, dict(sorted(st.items())), flush=True)
flags = {"date_flags": {"nodate_source_default": "ch_entscheidsuche indexes ids ending _nodate at 2021-01-01; r7 replaces that with the docket year (year precision) or NULL; see metadata.date_placeholder"}} if SRC == "ch_entscheidsuche" else {}
if not DRY:
    old = json.load(open(f"{sup}/summary.json"))
    keep = {k: old[k] for k in ("fails", "n_fails", "http_requests") if k in old}
    s = write_summary(SRC, migrated_from="r6", migrated_la=now_la(), r7_changes=dict(sorted(st.items())), previous_r6_summary={k: v for k, v in old.items() if k not in keep}, **flags, **keep)
    print(dump_unmatched(SRC, None)); print(json.dumps({k: s[k] for k in ("decisions_total_incl_resume", "rows_total", "shards_total", "bytes_total", "court_match")}))
    json.dump({"source": SRC, "stats": dict(sorted(st.items())), "lists": {k: v for k, v in lists.items()}}, open(f"{_LEGAL_WS}/case_law/logs/migrate_r7_{SRC}.json", "w"), indent=1, ensure_ascii=False, default=str)
else:
    json.dump({"source": SRC, "dry": True, "stats": dict(sorted(st.items())), "lists": {k: v for k, v in lists.items()}}, open(f"{_LEGAL_WS}/case_law/logs/dry_r7_{SRC}.json", "w"), indent=1, ensure_ascii=False, default=str)
