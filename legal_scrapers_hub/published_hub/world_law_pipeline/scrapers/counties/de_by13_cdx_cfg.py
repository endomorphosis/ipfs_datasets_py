"""2026-10-24 de_by13: archive-only config for a Landkreis whose live site cannot be crawled (robots.txt unreachable / Cloudflare 403) and
whose index pages have no archived copy, built from the Wayback CDX listing of archived PDFs (mimetype application/pdf, status 200).
Only law-relevant paths (keep_re) are kept; spreadsheets never match (PDF mimetype only). URLs normalised to https://www.<host>/path.
PDFs are fetched ONLY from Common Crawl / Wayback by archive_retry.py (same config format as archive_index_build / de_by12_index_cfg).
Usage: de_by13_cdx_cfg.py <entry.json> <platform> [max_urls]   entry: {"name","qid","iso","host","index_url","keep_re","drop_re","archive_policy"}"""
import re, sys, json, time, urllib.request, urllib.parse
from pathlib import Path
HERE = Path(__file__).parent; e = json.load(open(sys.argv[1])); PLAT = sys.argv[2]; MAXU = int(sys.argv[3]) if len(sys.argv) > 3 else 2000
q = "https://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode([("url", e["host"] + "/"), ("matchType", "prefix"), ("filter", "statuscode:200"),
    ("filter", "mimetype:application/pdf"), ("collapse", "urlkey"), ("fl", "original,timestamp"), ("limit", "50000")])
for t in range(6):
    try: rows = urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "worldlaw-archive/1.0"}), timeout=180).read().decode("utf-8", "replace").splitlines(); break
    except Exception as ex: print("cdx_err", t, ex, flush=True); time.sleep(120 * (t + 1))
else: print(e["name"], "cdx_unavailable"); sys.exit(1)
found = {}
for r in rows:
    p = r.split()
    if not p: continue
    s = urllib.parse.urlsplit(p[0]); path = s.path + (("?" + s.query) if s.query else "")
    u = "https://www." + e["host"] + path
    if not re.search(e["keep_re"], urllib.parse.unquote(path), re.I): continue
    if e.get("drop_re") and re.search(e["drop_re"], urllib.parse.unquote(path), re.I): continue
    if re.search(r"\.(xlsx?|ods|csv)(\?|$)", path, re.I): continue
    t = re.sub(r"[_+]+", " ", urllib.parse.unquote(path.rsplit("/", 1)[-1].split("?")[0]))
    t = re.sub(r"\.pdf$", "", t, flags=re.I).strip()
    found.setdefault(u, t)
print(e["name"], "cdx_rows", len(rows), "kept", len(found), flush=True)
slug = re.sub(r"\W+", "_", e["name"].lower()).strip("_"); cfgp = HERE / f"de_{PLAT}_{slug}_archive.json"
urls = sorted(found, key=lambda u: (not re.search(r"satzung|verordnung", u, re.I), u))[:MAXU]
json.dump(dict(country_code="DE", place_id="wd:" + e["qid"], qid=e["qid"], place_name=e["name"], iso_3166_2=e.get("iso"), admin_level="landkreis", language="de",
               doc_type="ordinance", platform="de_" + PLAT, source_org=e["name"], index_url=e["index_url"], archive_policy=e.get("archive_policy", "archived_robots_unreachable"),
               max_bytes=50 * 1024 * 1024, urls=urls, titles={u: found[u] for u in urls}), open(cfgp, "w"), ensure_ascii=False, indent=1)
print(e["name"], "config", cfgp, "urls", len(urls), flush=True)
