"""One-off: move live r5 shards (+manifest/summary/unmatched; rejected_rows.jsonl is COPIED) of a source to out/<src>/superseded/r5/ (NOTHING deleted) and rewrite the same rows as r6.
usage: migrate_r5_to_r6.py <source> [--dry]. Local data only; no fetching. r6 row changes:
  all: docket_number/court_name_raw normalised (whitespace, 'undefined' -> NULL, originals kept in metadata.normalised_labels); body_type; e-mail redaction (+rehash, personal_contact flag)
  CH : language 'ro' -> 'de' on wc1:decision:8f55402ab71f0aa6d07af15c; Jan-1 placeholder dates -> year precision (evidence in metadata.date_placeholder)
  NL : single-territory Aruba/Cura\u00e7ao/Sint Maarten courts -> country_iso AW/CW/SX (court key recomputed + rematched locally)"""
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
base = f"{OUT}/{SRC}"; sup = f"{base}/superseded/r5"
RO_ID = "wc1:decision:8f55402ab71f0aa6d07af15c"
print(now_la(), "start", SRC, "dry" if DRY else "LIVE", preflight("migrate r6 start"), flush=True)
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
    open(f"{sup}/SUPERSEDED.md", "w").write("Superseded 2026-10-29 by caselaw-raw/v0-r6 (schema_caselaw_v4.md). r5 shards kept for audit; rows rewritten from these shards (no refetch). "
        "r6 row changes: docket/court labels normalised ('undefined' -> NULL), body_type column, e-mail addresses redacted (+text_sha256, personal_contact flag), "
        "CH language fix + Jan-1 placeholder dates -> year precision, NL Aruba/Curacao/Sint Maarten courts -> AW/CW/SX. summary/unmatched regenerated from the data. "
        "rejected_rows.jsonl was copied (the live file stays).\n")
src_dir = (lambda k: f"{sup}/{k}") if not DRY else (lambda k: f"{base}/{k}")
matcher = None
st = collections.Counter(); lists = collections.defaultdict(list); n = {"decision": 0, "opinion": 0}
decp = sorted(glob.glob(f"{src_dir('decision')}/part-*.parquet")); opp = sorted(glob.glob(f"{src_dir('opinion')}/part-*.parquet"))
assert len(decp) == len(opp) and decp, (len(decp), len(opp))
de_words = re.compile(r"\b(der|die|das|und|nicht|mit|von|ist)\b", re.I); other_words = re.compile(r"\b(si|este|\u0219i|pentru|care|din)\b", re.I)
for i, (dp, op_) in enumerate(zip(decp, opp)):
    drows = pq.read_table(dp).to_pylist(); orows = {r["decision_id"]: r for r in pq.read_table(op_).to_pylist()}
    assert len(orows) == len(drows) and {r["id"] for r in drows} == set(orows), f"shard {i}: decision/opinion pairing differs"
    new_d, new_o = [], []
    for d in drows:
        o = orows[d["id"]]; ch = []
        if d["id"] == RO_ID:
            assert d["language"] == "ro" and "Erl\u00e4uterungen zum Ordnungsbussengesetz" in o["text"] and "sprache=d" in o["text"], "ro row evidence missing"
            for r in (d, o): r["language"] = "de"
            r6_rules._meta(d)["language_correction"] = {"from": "ro", "to": "de", "evidence": "opinion text is a German title (Erl\u00e4uterungen zum Ordnungsbussengesetz ...) with a sprache=d link; recheck_v3"}
            r6_rules._meta(o)["language_correction"] = {"from": "ro", "to": "de"}; ch.append("language"); lists["language_fixed"].append(d["id"])
        if SRC == "nl_rechtspraak":
            iso = r6_rules.nl_territory(d["court_name_raw"])
            if iso:
                matcher = matcher or CourtMatcher()
                ecli = d["source_record_id"]; cm = matcher.match(iso, d["court_name_raw"], source_name=SRC, discriminator=ecli.split(":")[2] if ecli.count(":") >= 2 else None)
                for r in (d, o): r["country_iso"] = iso
                d.update(court_entity_key=cm["court_entity_key"], court_key_provisional=cm["court_key_provisional"], court_match_status=cm["court_match_status"])
                dm = r6_rules._meta(d); dm.update(cm["meta"]); dm["country_correction"] = {"from": "NL", "to": iso, "reason": "single-territory court of the Kingdom of the Netherlands"}
                r6_rules._meta(o)["country_correction"] = {"from": "NL", "to": iso}
                ch.append("country"); st[f"nl_to_{iso}"] += 1; st[f"nl_to_{iso}_match_{cm['court_match_status']}"] += 1; lists["country_moved"].append((d["id"], iso))
            elif r6_rules.nl_territory(None) is None and any(t in (d["court_name_raw"] or "").casefold() for t, _ in r6_rules.TERRITORIES):
                st["nl_joint_court_kept_NL"] += 1; r6_rules._meta(d)["territory_note"] = "joint court for several Kingdom territories; country_iso stays NL"
        if SRC == "ch_entscheidsuche":
            ev = r6_rules.apply_ch_date(d, o["text"])
            if ev:
                r6_rules._meta(o); ch.append("date_year_precision"); st["ch_year_precision"] += 1; st["ch_year_precision__" + ev] += 1
        s = r6_rules.apply_r6(d, o)
        for k_ in ("labels", "emails", "body_type", "key"):
            if s[k_]: st[f"{k_}_rows" if k_ != "emails" else "emails_redacted"] += (1 if k_ != "emails" else s[k_]); ch.append(k_)
        if s["emails"]: st["email_rows"] += 1
        if d.get("body_type"): st["body_type__" + d["body_type"]] += 1
        else: st["body_type__NULL"] += 1
        if ch: r6_rules._meta(d)["r6_migration"] = {"from": "r5", "changes": sorted(set(ch))}; r6_rules._meta(o)["r6_migration"] = {"from": "r5", "changes": sorted(set(ch))}
        new_d.append(d); new_o.append(o)
    for kind, rows in (("decision", new_d), ("opinion", new_o)):
        t = cs.cast_rows(rows, kind)
        final = f"{base}/{kind}/part-{i:04d}.parquet"; tmp = f"{base}/{kind}/.part-{i:04d}.parquet.writing"
        if DRY:
            pr = cs.validate_caselaw_table(t, kind); assert not pr, pr; n[kind] += t.num_rows; continue
        os.makedirs(f"{base}/{kind}", exist_ok=True)
        size = cs.write_shard(t, tmp, kind); os.replace(tmp, final); n[kind] += t.num_rows
        with open(f"{base}/manifest.jsonl", "a") as f:
            f.write(json.dumps({"time_la": now_la(), "path": final, "record_type": kind, "rows": t.num_rows, "bytes": size, "migrated_from": "r5", **preflight("migrate r6")}) + "\n")
        print(final, t.num_rows, size, flush=True)
# summary line for the lists
for k_, v in lists.items(): st["list_" + k_] = len(v)
print(now_la(), "rows", n, dict(sorted(st.items())), flush=True)
if not DRY:
    old = json.load(open(f"{sup}/summary.json"))
    keep = {k: old[k] for k in ("fails", "n_fails", "http_requests") if k in old}
    s = write_summary(SRC, migrated_from="r5", migrated_la=now_la(), r6_changes=dict(sorted(st.items())), previous_r5_summary={k: v for k, v in old.items() if k not in keep}, **keep)
    print(dump_unmatched(SRC, matcher)); print(json.dumps({k: s[k] for k in ("decisions_total_incl_resume", "rows_total", "shards_total", "bytes_total", "court_match")}))
    json.dump({"source": SRC, "stats": dict(sorted(st.items())), "lists": {k: v for k, v in lists.items()}}, open(f"{_LEGAL_WS}/case_law/logs/migrate_r6_{SRC}.json", "w"), indent=1, ensure_ascii=False)
