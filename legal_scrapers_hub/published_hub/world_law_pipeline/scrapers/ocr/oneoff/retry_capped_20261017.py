"""One-off (2026-10-17): give each 5-attempt-capped transient doc exactly one more fetch with pdf_collect's own
fetch/staging path, while the collector is stopped. Success -> sealed batch (same format as seal()); failure -> gave_up (terminal)."""
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, os, re, sys
from collections import Counter
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr"))
import pdf_collect as pc
import ocr_afme as A
pc.ROBOTS = pc.Robots(pc.STATE / "robots")
attf = pc.STATE / "attempts.json"; attempts = json.loads(attf.read_text())
donef = pc.STATE / "done.txt"; done = set(donef.read_text().split("\n"))
def key(it): return f"{it['lane']}|{it['place_id'] or ''}|{it['doc_id']}" + (f"|{it['key_extra']}" if it.get("key_extra") else "")
want = set(sys.argv[1:])
items = [it for it in pc.load_council("ro") if key(it) in want]
rows = pc.jl_snapshot(pc.SRC["afme"]); mirror = A.load_mirror({(e["place_id"], e["doc_id"]) for e in rows})
for e in rows:
    it = pc.item("afme", e["doc_id"], e["place_id"], e["country_code"], e["source_url"], e.get("source_policy"),
                 A.candidates(e, mirror.get((e["place_id"], e["doc_id"])) or e), archive=(e.get("extra_metadata") or {}).get("archive"))
    if key(it) in want and key(it) not in {key(x) for x in items}: items.append(it)
print("items", len(items), "of", len(want), flush=True)
nums = [int(m.group(1)) for p in pc.MAN.glob("batch_*") if (m := re.match(r"batch_(\d{4})", p.name))]
bn = max(nums, default=0) + 1; ok_rows, ok_keys, res = [], [], []
skipf = open(pc.LOGS / "skipped.jsonl", "a", encoding="utf-8"); fetf = open(pc.LOGS / "fetched.jsonl", "a", encoding="utf-8")
def logskip(it, reason, detail):
    skipf.write(json.dumps({"ts": pc.utcnow(), "lane": it["lane"], "doc_id": it["doc_id"], "place_id": it["place_id"], "country_code": it["country_code"],
        "source_url": it["source_url"], "source_policy": it["source_policy"], "reason": reason, "detail": str(detail)[:300], "terminal": True}, ensure_ascii=False) + "\n"); skipf.flush()
for it in items:
    k = key(it)
    if pc.shutil.disk_usage("/workspace").free < 35e9 or pc.dir_bytes(pc.ROOT) + pc.MAX_BYTES > 10e9: print("SPACE LIMIT, stop"); break
    d = pc.ROOT / it["country_code"] / it["place_key"]; nm = pc.safe(it["doc_id"])
    if nm[:1] in "._" or len(nm.encode()) > 240 or (d / (nm + ".pdf")).exists(): nm = pc.alt_name(it["doc_id"])
    dest = d / (nm + ".pdf"); st = None
    try: r = pc.fetch(it, dest); st = "ok"
    except pc.Skip as s: st, reason, detail = "skip", s.reason, s.detail
    except pc.Retry as x: st, reason, detail = "fail", "gave_up_transient", f"{attempts.get(k,0)+1} attempts; last: {x}"
    except Exception as x: st, reason, detail = "fail", "gave_up_error", f"{attempts.get(k,0)+1} attempts; last: {x!r}"[:300]
    if st == "ok":
        tmp = dest.with_name(dest.name + ".tmp"); ch = pc.text_chars(tmp)
        if ch >= 200: tmp.unlink(missing_ok=True); st, reason, detail = "skip", "has_text_layer", f"PDF has a usable text layer ({ch} chars, PDF_STAGING.md §1)"
    if st == "ok":
        os.rename(tmp, dest)
        row = {"doc_id": it["doc_id"], "place_id": it["place_id"], "place_key": it["place_key"], "country_code": it["country_code"], "source_url": r["url"],
               "sha256": r["sha256"], "bytes": r["bytes"], "fetched_at": pc.utcnow(), "source_policy": it["source_policy"], "lane": it["lane"]}
        if dest.stem != pc.safe(it["doc_id"]): row["pdf_file"] = str(dest.relative_to(pc.ROOT))
        ok_rows.append(row); ok_keys.append(k)
        fetf.write(json.dumps({"ts": row["fetched_at"], "lane": it["lane"], "doc_id": it["doc_id"], "via": r["via"], "url": r["url"]}, ensure_ascii=False) + "\n"); fetf.flush()
        res.append({"key": k, "result": "recovered", "via": r["via"], "bytes": r["bytes"]})
    else:
        if st == "fail": attempts[k] = attempts.get(k, 0) + 1
        logskip(it, reason, detail)
        with open(donef, "a") as f: f.write(k + "\n")
        res.append({"key": k, "result": "failed" if st == "fail" else "terminal_skip", "reason": reason, "detail": str(detail)[:200]})
    print(json.dumps(res[-1], ensure_ascii=False), flush=True)
    t = attf.with_name(attf.name + ".tmp"); t.write_text(json.dumps(attempts)); os.replace(t, attf)
if ok_rows:
    bn = pc.BA.write_batch(pc.MAN, ok_rows); fin = pc.MAN / f"batch_{bn:04d}.jsonl"     # shared allocator, .ready last
    with open(donef, "a") as f:
        for k in ok_keys: f.write(k + "\n")
    with open(pc.LOGS / "events.log", "a") as f: f.write(f"{pc.utcnow()} oneoff retry_capped sealed {fin.name} rows={len(ok_rows)} lanes={dict(Counter(r['lane'] for r in ok_rows))}\n")
print("SUMMARY", json.dumps(res, ensure_ascii=False))
