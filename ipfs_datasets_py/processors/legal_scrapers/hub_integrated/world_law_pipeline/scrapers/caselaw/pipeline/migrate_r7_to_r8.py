"""One-off: move live r7 shards (+manifest/summary/unmatched; rejected_rows.jsonl is COPIED) of a source to out/<src>/superseded/r7/ (NOTHING deleted) and rewrite the same rows as r8.
usage: migrate_r7_to_r8.py <source> [--dry]. Local data only; no fetching. r8 row changes (r6_rules.apply_r8), CH only: the 2 GR `_0000-00-00` rows flagged date_unknown; the 8 AR Kantonsgericht ARGVP rows
decision_date/year NULL + metadata.publication_year; the 7 AR Obergericht O-series rows full date from the 'Urteil|Beschluss vom' heading; BGE 34 I 386 and 32 I 800 full date from the anchored 'arret du' phrase.
All sources: shards re-stamped schema_doc_version caselaw-raw/v0-r8; the validator now requires date_unknown on every NULL decision_date."""
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
base = f"{OUT}/{SRC}"; sup = f"{base}/superseded/r7"
print(now_la(), "start", SRC, "dry" if DRY else "LIVE", preflight("migrate r8 start"), flush=True)
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
    open(f"{sup}/SUPERSEDED.md", "w").write("Superseded 2026-10-29 by caselaw-raw/v0-r8 (schema_caselaw_v6.md). r7 shards kept for audit; rows rewritten from these shards (no refetch). "
        "r8 row changes (CH only): 2 GR _0000-00-00 rows flagged date_unknown; 8 AR Kantonsgericht ARGVP rows decision_date/year NULL with metadata.publication_year; 7 AR Obergericht O-series rows full date from the heading; "
        "BGE 34 I 386 and 32 I 800 full date from the anchored 'arret du' phrase. All sources re-stamped r8 (validator: a NULL decision_date needs date_unknown). "
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
        s = r6_rules.apply_r8(d, o); ch = []
        if s["date8"]: ch.append("date8_" + s["date8"]); st["date8_" + s["date8"]] += 1; lists["date8_" + s["date8"]].append((d["source_record_id"], d["decision_date"], d["decision_year"]))
        if s["tg_strip"]: ch.append("tg_nav_stripped"); st["tg_stripped"] += 1; lists["tg_stripped"].append(d["id"])
        if s["date"]: ch.append("date_" + s["date"]); st["date_" + s["date"]] += 1; lists["date_" + s["date"]].append((d["source_record_id"], d["decision_date"]))
        if s["emails"]: ch.append("emails"); st["emails_redacted"] += s["emails"]; st["email_rows"] += 1
        if s["not_decision"]: ch.append("not_decision"); st["not_decision"] += 1; lists["not_decision"].append(d["id"])
        if d.get("body_type") != before_bt: ch.append("body_type"); st["body_type_changed"] += 1; lists["body_type_changes"].append((before_bt, d.get("body_type")))
        if s["labels"]: ch.append("labels")
        st["body_type__" + str(d.get("body_type"))] += 1
        if ch:
            for r_ in (d, o): r6_rules._meta(r_)["r8_migration"] = {"from": "r7", "changes": sorted(set(ch))}
        new_d.append(d); new_o.append(o)
    for kind, rows in (("decision", new_d), ("opinion", new_o)):
        t = cs.cast_rows(rows, kind)
        final = f"{base}/{kind}/part-{i:04d}.parquet"; tmp = f"{base}/{kind}/.part-{i:04d}.parquet.writing"
        if DRY:
            pr = cs.validate_caselaw_table(t, kind); assert not pr, pr; n[kind] += t.num_rows; continue
        os.makedirs(f"{base}/{kind}", exist_ok=True)
        size = cs.write_shard(t, tmp, kind); os.replace(tmp, final); n[kind] += t.num_rows
        with open(f"{base}/manifest.jsonl", "a") as f:
            f.write(json.dumps({"time_la": now_la(), "path": final, "record_type": kind, "rows": t.num_rows, "bytes": size, "migrated_from": "r7", **preflight("migrate r8")}) + "\n")
        print(final, t.num_rows, size, flush=True)
for k_, v in lists.items(): st["list_" + k_] = len(v)
print(now_la(), "rows", n, dict(sorted(st.items())), flush=True)
flags = {"date_flags": {"nodate_source_default": "ch_entscheidsuche indexes ids ending _nodate at 2021-01-01; r7 replaced that with the docket year (year precision) or NULL; r8: 8 AR ARGVP rows NULL + metadata.publication_year (ARGVP volume year, not a decision year), 7 AR O-series rows recovered from the heading; see metadata.date_placeholder", "null_dates": "every NULL decision_date carries metadata.date_placeholder.date_unknown=true (validator rule since r8)"}} if SRC == "ch_entscheidsuche" else {}
if not DRY:
    old = json.load(open(f"{sup}/summary.json"))
    keep = {k: old[k] for k in ("fails", "n_fails", "http_requests") if k in old}
    s = write_summary(SRC, migrated_from="r7", migrated_la=now_la(), r8_changes=dict(sorted(st.items())), previous_r7_summary={k: v for k, v in old.items() if k not in keep}, **flags, **keep)
    print(dump_unmatched(SRC, None)); print(json.dumps({k: s[k] for k in ("decisions_total_incl_resume", "rows_total", "shards_total", "bytes_total", "court_match")}))
    json.dump({"source": SRC, "stats": dict(sorted(st.items())), "lists": {k: v for k, v in lists.items()}}, open(f"{_LEGAL_WS}/case_law/logs/migrate_r8_{SRC}.json", "w"), indent=1, ensure_ascii=False, default=str)
else:
    json.dump({"source": SRC, "dry": True, "stats": dict(sorted(st.items())), "lists": {k: v for k, v in lists.items()}}, open(f"{_LEGAL_WS}/case_law/logs/dry_r8_{SRC}.json", "w"), indent=1, ensure_ascii=False, default=str)
