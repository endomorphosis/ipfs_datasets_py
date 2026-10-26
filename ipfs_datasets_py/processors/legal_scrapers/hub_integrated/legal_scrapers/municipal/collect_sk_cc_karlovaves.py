#!/usr/bin/env python3
"""Bratislava-Karlova Ves (obec code 529397) from Common Crawl only (www.karlovaves.sk times out for us).
Ranged WARC reads of the captured index page /zverejnovanie/vseobecne-zavazne-nariadenia/ (anchor 'VZN č. N/YYYY' + the
following description) and of the captured PDFs it links (path_prefix wp-content/uploads). The site's robots.txt as
captured by Common Crawl is honoured. Acts whose PDF was never captured are reported as errors.
Usage: collect_sk_cc_karlovaves.py OUT.jsonl"""
import json, re, sys, os, html as H, urllib.robotparser
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.environ.get("LEGAL_SCRAPERS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
import common_crawl_helper as cc
from sk_common import doc_text, clean, write_jsonl
D, IDX = "karlovaves.sk", "https://www.karlovaves.sk/zverejnovanie/vseobecne-zavazne-nariadenia/"
strip = lambda s: re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()
cols = cc.recent_collections(6)
def latest(ps):
    best = {}
    for p in ps:
        u = p["url"].split("?")[0]
        if u not in best or p["timestamp"] > best[u]["timestamp"]: best[u] = p
    return best
rob = latest(cc.find_pointers(D, cols, path_prefix="/robots.txt", max_records=20, dedupe_url=False))
rp = urllib.robotparser.RobotFileParser()
rr = [r for r in cc.fetch_records(list(rob.values())[:1]) if r.get("body")]
rp.parse(rr[0]["body"].decode("utf-8", "replace").splitlines() if rr else [])
ok = lambda u: rp.can_fetch("*", u)
idx = latest(cc.find_pointers(D, cols, path_prefix="/zverejnovanie/vseobecne-zavazne-nariadenia", max_records=50, dedupe_url=False))
page = [r for r in cc.fetch_records([idx[IDX]]) if r.get("body")][0]
h = page["body"].decode("utf-8", "replace")
# each act: <a href="...pdf">VZN č. N/YYYY</a>, description up to the next anchor/line break
acts, seen = [], set()
for m in re.finditer(r'(?s)<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>(.{0,600}?)(?=<a |<br|</p>|</li>)', h):
    url, anc, tail = m.group(1), strip(m.group(2)), strip(m.group(3))
    num = re.search(r"(\d+)\s*/\s*(\d{4})", anc)
    if not num or re.search(r"(?i)pr[ií]loh", anc) or url in seen: continue
    seen.add(url)
    acts.append(dict(url=url, num=f"{num.group(1)}/{num.group(2)}", title=(anc + " " + tail.lstrip(", ")).strip()))
print("discovered", len(acts), flush=True)
pdfs = latest(cc.find_pointers(D, list(dict.fromkeys(cols + cc.spread_collections(24))), mime_regex="pdf", path_prefix="/wp-content/uploads", max_records=20000, max_blocks_per_collection=40))
out, errs = [], {}
for a in acts:
    nid = "vzn-" + a["num"].replace("/", "-")
    if not ok(a["url"]): errs[nid] = "robots.txt disallows"; continue
    p = pdfs.get(a["url"].split("?")[0])
    if not p: errs[nid] = "pdf not captured by Common Crawl"; continue
    r = cc.fetch_records([p])[0]
    if not r.get("body"): r = cc.fetch_records([p])[0]                       # one retry
    if not r.get("body"): errs[nid] = r.get("error", "no body"); continue
    tt, how = doc_text(r["body"], {"ctype": "application/pdf", "url": a["url"]})
    out.append(dict(municipality="Bratislava-Karlova Ves", municipality_code="529397", native_id=nid, source_url=a["url"], page_url=IDX,
                    title=a["title"], retrieved_at=f"{p['timestamp'][:4]}-{p['timestamp'][4:6]}-{p['timestamp'][6:8]}T{p['timestamp'][8:10]}:{p['timestamp'][10:12]}:{p['timestamp'][12:14]}Z",
                    text=clean(tt), extras=dict(reg_number=a["num"], extraction=how, via="common_crawl", cc_collection=p["collection"], cc_timestamp=p["timestamp"],
                                                index_capture=page["timestamp"], status_source="karlovaves.sk VZN index (current acts by topic; no repeal data)")))
write_jsonl(sys.argv[1], out)
json.dump(dict(discovered=len(acts), records=len(out), errors=errs), open(sys.argv[1] + ".stats.json", "w"), ensure_ascii=False, indent=1)
print("done", len(out), len(errs), dict(__import__("collections").Counter(errs.values())))
