#!/usr/bin/env python3
"""Verify the staged KE batch (Samburu County Assembly Acts) alone and combined with the live KE shards.

Usage: python3 verify_ke_samburu.py --pack <pack dir> --live <dir with data/*.parquet downloaded read-only from the Hub>
       [--stage <stage dir with requests.jsonl>] [--shard 00002] [--batch batch2]
Checks: schema equality with the live shards, id / work-key (eli) uniqueness, orphan articles, article_count vs rows,
empty texts, duplicate article ids, Samburu absence in the live shards (municipality_id, title, work key),
per-host minimum gap between sends (all request logs that share the host), request log table in PT, sha256 + bytes.
"""
import argparse, glob, hashlib, json, os, re, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pyarrow.parquet as pq

PT = timezone(timedelta(hours=-7), "PT")   # America/Los_Angeles in October (PDT, UTC-7)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def check(laws, arts, label):
    out = {"label": label, "laws": len(laws), "articles": len(arts)}
    ids = [l["id"] for l in laws]
    out["dup_law_ids"] = [k for k, v in Counter(ids).items() if v > 1]
    elis = [l["eli"] for l in laws]
    out["dup_work_keys"] = [k for k, v in Counter(elis).items() if v > 1]
    out["dup_official_identifier"] = [k for k, v in Counter(l["official_identifier"] for l in laws).items() if v > 1]
    aids = [a["id"] for a in arts]
    out["dup_article_ids"] = [k for k, v in Counter(aids).items() if v > 1]
    idset = set(ids)
    out["orphan_articles"] = sum(1 for a in arts if a["law_id"] not in idset)
    per = Counter(a["law_id"] for a in arts)
    out["article_count_mismatch"] = [l["id"] for l in laws if (l["article_count"] or 0) != per.get(l["id"], 0)]
    out["empty_law_text"] = [l["id"] for l in laws if not (l["text"] or "").strip()]
    out["empty_law_title"] = [l["id"] for l in laws if not (l["title"] or "").strip()]
    out["empty_article_text"] = [a["id"] for a in arts if not (a["text"] or "").strip()]
    out["article_id_prefix_bad"] = [a["id"] for a in arts if not a["id"].startswith(a["law_id"] + "-s-")]
    out["law_id_scheme_bad"] = [l["id"] for l in laws if not l["id"].startswith("ke-muni-")]
    out["ok"] = not any(out[k] for k in ("dup_law_ids", "dup_work_keys", "dup_official_identifier", "dup_article_ids", "orphan_articles",
                                         "article_count_mismatch", "empty_law_text", "empty_law_title", "empty_article_text",
                                         "article_id_prefix_bad", "law_id_scheme_bad"))
    return out


def gaps(stage):
    """Per-host minimum gap between consecutive sends over every request log that mentions the host."""
    logs = sorted(set(glob.glob(str(Path(stage) / "requests.jsonl")) + glob.glob("/dev/shm/muni_africa/*/*/requests.jsonl")
                      + glob.glob("/dev/shm/muni_africa/*/requests.jsonl") + glob.glob("/dev/shm/muni_africa/next_probe/*requests*.jsonl")))
    own = []
    for l in open(Path(stage) / "requests.jsonl"):
        own.append(json.loads(l))
    hosts = sorted({r["url"].split("/")[2] for r in own})
    res = {}
    for h in hosts:
        sends = []
        for lp in logs:
            try:
                for line in open(lp):
                    if h not in line:
                        continue
                    r = json.loads(line)
                    if r.get("url", "").split("/")[2] != h:
                        continue
                    sa = r.get("sent_at") or []
                    for t in ([sa] if isinstance(sa, str) else sa):
                        sends.append((datetime.fromisoformat(t.replace("Z", "+00:00")), lp))
            except (OSError, ValueError):
                continue
        sends = sorted(set(sends))
        g = [(b[0] - a[0]).total_seconds() for a, b in zip(sends, sends[1:])]
        res[h] = {"sends_all_logs": len(sends), "logs": sorted({p for _, p in sends}),
                  "min_gap_s": round(min(g), 4) if g else None, "pacer_floor_s": 5.0, "ok": (min(g) >= 5.0) if g else True}
    table = []
    for r in own:
        for t in r.get("sent_at") or []:
            ts = datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(PT)
            table.append({"sent_pt": ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " PT", "host": r["url"].split("/")[2],
                          "kind": r.get("kind") or ("pdf" if r["url"].endswith(".pdf") else "html"), "status": r.get("status"),
                          "url": r["url"]})
    table.sort(key=lambda x: x["sent_pt"])
    return res, table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True)
    ap.add_argument("--live", required=True)
    ap.add_argument("--stage", default=os.environ.get("MUNI_STAGE", "/dev/shm/muni_africa/ke/samburu"))
    ap.add_argument("--shard", default="00002")
    ap.add_argument("--batch", default="batch2")
    a = ap.parse_args()
    pack, live = Path(a.pack), Path(a.live)
    lp, ap_ = pack / "data" / f"laws-{a.shard}.parquet", pack / "data" / f"articles-{a.shard}.parquet"
    L, A = pq.read_table(lp), pq.read_table(ap_)
    live_l = [pq.read_table(p) for p in sorted(live.glob("data/laws-*.parquet"))]
    live_a = [pq.read_table(p) for p in sorted(live.glob("data/articles-*.parquet"))]
    rep = {"generated_at_pt": datetime.now(PT).strftime("%Y-%m-%d %H:%M:%S PT")}
    rep["schema_equal_laws"] = all(t.schema.equals(L.schema, check_metadata=False) for t in live_l)
    rep["schema_equal_articles"] = all(t.schema.equals(A.schema, check_metadata=False) for t in live_a)
    rep["schema_laws"] = [f"{f.name}:{f.type}" for f in L.schema]
    laws, arts = L.to_pylist(), A.to_pylist()
    rep["batch"] = check(laws, arts, "batch alone")
    rep["batch"]["municipality_ids"] = sorted({l["municipality_id"] for l in laws})
    rep["batch"]["qids"] = sorted({l["wikidata_qid"] for l in laws} | {x["wikidata_qid"] for x in arts})
    rep["batch"]["law_status"] = dict(Counter(l["law_status"] for l in laws))
    rep["batch"]["source_hosts"] = sorted({l["source_url"].split("/")[2] for l in laws})
    rep["batch"]["articles_min_max_per_law"] = [min(l["article_count"] for l in laws), max(l["article_count"] for l in laws)] if laws else None
    lv_laws = [r for t in live_l for r in t.to_pylist()]
    lv_arts = [r for t in live_a for r in t.to_pylist()]
    rep["live"] = {"laws": len(lv_laws), "articles": len(lv_arts), "municipalities": len({l["municipality_id"] for l in lv_laws})}
    sam_live = [l["id"] for l in lv_laws if l["municipality_id"] == "ke-025" or "samburu" in (l["title"] or "").lower()
                or l["eli"].startswith("/akn/ke-025/")]
    bt = {norm_title(l["title"]): l["id"] for l in laws}
    rep["samburu_absent_in_live"] = {"rows_with_ke-025_or_samburu_title_or_work": sam_live,
                                     "title_collisions": sorted(bt[t] for t in {norm_title(l["title"]) for l in lv_laws} & set(bt)),
                                     "work_key_collisions": sorted({l["eli"] for l in laws} & {l["eli"] for l in lv_laws}),
                                     "law_id_collisions": sorted({l["id"] for l in laws} & {l["id"] for l in lv_laws}),
                                     "article_id_collisions": len({x["id"] for x in arts} & {x["id"] for x in lv_arts})}
    rep["samburu_absent_in_live"]["ok"] = not any(rep["samburu_absent_in_live"][k] for k in rep["samburu_absent_in_live"] if k != "ok")
    base = check(lv_laws, lv_arts, "live shards alone (baseline)")
    comb = check(lv_laws + laws, lv_arts + arts, "live shards + batch")
    keys = [k for k, v in comb.items() if isinstance(v, list)]
    new = {k: sorted(set(map(str, comb[k])) - set(map(str, base[k]))) for k in keys}
    new["orphan_articles"] = comb["orphan_articles"] - base["orphan_articles"]
    rep["live_baseline_preexisting"] = {k: (len(base[k]) if isinstance(base[k], list) else base[k]) for k in base if k not in ("label", "ok")}
    rep["combined"] = {"laws": comb["laws"], "articles": comb["articles"],
                       "municipalities": len({l["municipality_id"] for l in lv_laws + laws}),
                       "issues_introduced_by_batch": new, "ok": not any(new.values())}
    g, table = gaps(a.stage)
    rep["pacing"] = g
    rep["request_log_pt"] = table
    files = {}
    for p in sorted(pack.rglob("*")):
        if p.is_file():
            files[str(p.relative_to(pack))] = {"bytes": p.stat().st_size, "sha256": sha(p)}
    rep["files"] = files
    rep["top_level_readme_absent"] = not (pack / "README.md").exists()
    sr = json.loads((pack / "manifests" / f"{a.batch}_stage_result.json").read_text())
    rep["stage_result_shas_match"] = all(sr[f"data/{p.name}"]["sha256"] == files[f"data/{p.name}"]["sha256"] for p in (lp, ap_))
    ok = (rep["schema_equal_laws"] and rep["schema_equal_articles"] and rep["batch"]["ok"] and rep["combined"]["ok"]
          and rep["samburu_absent_in_live"]["ok"] and all(v["ok"] for v in g.values()) and rep["top_level_readme_absent"]
          and rep["stage_result_shas_match"])
    rep["ALL_OK"] = ok
    print(json.dumps(rep, indent=1, ensure_ascii=False, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
