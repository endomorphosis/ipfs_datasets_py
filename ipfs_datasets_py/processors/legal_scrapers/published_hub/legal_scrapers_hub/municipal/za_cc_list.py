"""Selective Common Crawl index listing for ZA municipal sources (cluster.idx binary search + the few cdx blocks that
cover one SURT prefix; no dumps, no WARC reads here). Resumable: one done-marker per (collection, prefix).
Usage: za_cc_list.py OUT_DIR N_COLLECTIONS SURT_PREFIX [SURT_PREFIX ...]
Writes OUT_DIR/pointers.jsonl (all 200 captures) and OUT_DIR/done.txt."""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import common_crawl_helper as cc
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import za_common as zc

out, ncoll, prefixes = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
os.makedirs(out, exist_ok=True)
donef = os.path.join(out, "done.txt")
done = set(open(donef).read().split("\n")) if os.path.exists(donef) else set()
colls = cc.recent_collections(ncoll) if ncoll <= 12 else cc.spread_collections(ncoll)
print(zc.now_utc(), "collections", colls, flush=True)
for coll in colls:
    for pre in prefixes:
        key = f"{coll}\t{pre}"
        if key in done:
            continue
        if not zc.wait_resources(log=lambda m: print(m, flush=True)):
            sys.exit(3)
        try:
            blocks = cc.cluster_blocks(coll, pre)
        except Exception as e:
            print("cluster fail", coll, pre, e, flush=True); continue
        n = 0
        with open(os.path.join(out, "pointers.jsonl"), "a") as f:
            for blk in blocks[:60]:
                try:
                    lines = cc._read_cdx_block(coll, blk)
                except Exception as e:
                    print("block fail", coll, e, flush=True); continue
                for ln in lines:
                    if not ln.startswith(pre.encode()):
                        continue
                    try:
                        surt, ts, js = ln.decode("utf-8", "replace").split(" ", 2); j = json.loads(js)
                    except Exception:
                        continue
                    if str(j.get("status")) != "200":
                        continue
                    f.write(json.dumps(dict(url=j.get("url"), timestamp=ts, collection=coll, filename=j.get("filename"),
                                            offset=int(j.get("offset", 0)), length=int(j.get("length", 0)), status="200",
                                            mime=j.get("mime-detected") or j.get("mime"), digest=j.get("digest"))) + "\n")
                    n += 1
        print(zc.now_utc(), coll, pre, "blocks", len(blocks), "rows", n, flush=True)
        with open(donef, "a") as f:
            f.write(key + "\n")
print(zc.now_utc(), "DONE", flush=True)
