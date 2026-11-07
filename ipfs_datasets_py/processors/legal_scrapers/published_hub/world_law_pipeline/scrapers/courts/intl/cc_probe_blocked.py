"""Probe Common Crawl CDX + Wayback CDX for blocked court sites (polite, 5s, single connection). Writes cc_probe.jsonl."""
import json, time, urllib.request, urllib.parse, sys
UA = "WorldCourtsResearchBot/1.0 (+public court directory research; polite 5s crawl)"
DOM = ["lhc.gov.pk", "sierju.ramajudicial.gov.co", "pj.gob.pe", "toaan.gov.vn", "opendata.coj.go.th", "judiciary.lk", "judiciary.gov.gy",
       "poderjudicial.gob.do", "courts.bs", "csj.gob.sv", "poderjudicial.gob.hn", "cjf.gob.mx", "coj.go.th", "pjn.gov.ar", "gdcatalog.go.th"]
CC = ["CC-MAIN-2026-43", "CC-MAIN-2026-17", "CC-MAIN-2025-47"]
KW = ("direct", "contact", "court", "sede", "juzg", "tribunal", "address", "ubicac", "formato", "xls", "pdf", "csv", "listado", "dependenc")
out = open(sys.argv[1], "w")
def get(u):
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=120); return r.status, r.read().decode("utf-8", "replace")
    except Exception as e: return getattr(e, "code", 0), str(e)
    finally: time.sleep(5)
for d in DOM:
    for c in CC:
        st, body = get(f"https://index.commoncrawl.org/{c}-index?url=*.{d}&output=json&limit=3000&filter=status:200")
        recs = [json.loads(l) for l in body.splitlines() if l.startswith("{")]
        hits = [r for r in recs if any(k in r["url"].lower() for k in KW)]
        out.write(json.dumps({"src": "cc", "dom": d, "crawl": c, "status": st, "n": len(recs), "hits": hits[:400]}) + "\n"); out.flush()
        print(d, c, st, len(recs), len(hits), flush=True)
    st, body = get(f"https://web.archive.org/cdx/search/cdx?url={d}/*&output=json&limit=3000&filter=statuscode:200&collapse=urlkey")
    try: rows = json.loads(body)[1:]
    except Exception: rows = []
    hits = [r for r in rows if any(k in r[2].lower() for k in KW)]
    out.write(json.dumps({"src": "wayback", "dom": d, "status": st, "n": len(rows), "hits": hits[:400]}) + "\n"); out.flush()
    print(d, "wayback", st, len(rows), len(hits), flush=True)
