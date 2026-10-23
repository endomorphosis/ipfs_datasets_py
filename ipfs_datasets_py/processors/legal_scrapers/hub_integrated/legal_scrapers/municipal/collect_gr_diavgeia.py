#!/usr/bin/env python3
"""Greek municipal regulatory acts from Diavgeia (diavgeia.gov.gr open-data API).

Stage `discover`: for each municipality in munis.json (largest first), query
  /opendata/search/advanced.json  organizationUid:"<uid>" AND (subject:"κανονισμός" OR subject:"κανονιστική"
  OR subject:"εσωτερικής υπηρεσίας") AND issueDate:[six-month window]
over six-month windows 2010-10-01 .. today (the API caps a query window at ~6 months), size 500, paginated.
Every hit is written to discovery.jsonl; classify() then keeps only real regulations (see gr_fixes.classify_subject).
Stage `fetch`: download the decision PDF from /opendata/decisions/{ADA}/document (robots.txt disallows /doc/* and
/decision/view, so documentUrl is NOT used), cap ~3000 acts or ~1 GB, extract with pdftotext (no OCR).
Polite: robots.txt honoured, 1 req/s, disk cache (GR_CACHE)."""
import json, os, sys, time, datetime, shutil
from urllib.parse import quote, urlencode
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gr_common import Polite
from gr_fixes import classify_subject

B = os.environ.get("GR_BUILD", "gr_build")
API = "https://diavgeia.gov.gr/opendata"
P = Polite(1.0)
P.s.headers["Accept"] = "application/json"

def disk_ok():
    return shutil.disk_usage(os.path.dirname(os.path.abspath(B))).free / 2**30 >= 30

def windows(start=datetime.date(2010, 10, 1), end=None):
    end = end or datetime.date.today()
    a = start
    while a <= end:
        m = a.month + 6; y = a.year + (m - 1) // 12; m = (m - 1) % 12 + 1
        b = min(datetime.date(y, m, 1) - datetime.timedelta(days=1), end)
        yield a, b
        a = b + datetime.timedelta(days=1)

def search(q, page):
    u = API + "/search/advanced.json?" + urlencode({"q": q, "size": 500, "page": page})
    data, meta = P.get(u, timeout=120)
    return json.loads(data)

def discover():
    munis = json.load(open(f"{B}/munis.json"))
    out = open(f"{B}/discovery.jsonl", "a"); seen = set()
    if os.path.exists(f"{B}/discovery.jsonl"):
        for l in open(f"{B}/discovery.jsonl"):
            try: seen.add(json.loads(l)["ada"])
            except Exception: pass
    for m in munis:
        n0 = len(seen)
        for a, b in windows():
            q = (f'organizationUid:"{m["uid"]}" AND (subject:"κανονισμός" OR subject:"κανονιστική" OR subject:"εσωτερικής υπηρεσίας") '
                 f'AND issueDate:[DT({a}T00:00:00) TO DT({b}T23:59:59)]')
            page = 0
            while True:
                try: d = search(q, page)
                except Exception as e:
                    print("ERR", m["kal"], a, e, flush=True); break
                if d.get("errors"): print("APIERR", m["kal"], a, d["errors"], flush=True); break
                for x in d.get("decisions", []):
                    if x["ada"] in seen: continue
                    seen.add(x["ada"]); x["_kal"] = m["kal"]; x["_window"] = [str(a), str(b)]
                    out.write(json.dumps(x, ensure_ascii=False) + "\n")
                tot = d.get("info", {}).get("total", 0)
                if (page + 1) * 500 >= tot: break
                page += 1
        out.flush(); print(m["kal"], m["name"], "new", len(seen) - n0, flush=True)

def classify():
    stats = {}; keep = []
    for l in open(f"{B}/discovery.jsonl"):
        x = json.loads(l)
        ok, reason = classify_subject(x.get("subject") or "", x.get("decisionTypeId"))
        stats[reason] = stats.get(reason, 0) + 1
        x["_class"] = reason
        if ok: keep.append(x)
    json.dump(stats, open(f"{B}/classify_stats.json", "w"), ensure_ascii=False, indent=1)
    with open(f"{B}/candidates.jsonl", "w") as f:
        for x in keep: f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(json.dumps(stats, ensure_ascii=False, indent=1)); print("keep", len(keep))

def fetch(cap_n=3000, cap_bytes=int(os.environ.get("GR_CAP_BYTES", 2_000_000_000))):
    # interleaved across municipalities (round-robin in population order, newest act first within each) so every city gets acts
    rank = {m["kal"]: i for i, m in enumerate(json.load(open(f"{B}/munis.json")))}
    per = {}
    for l in open(f"{B}/candidates.jsonl"):
        x = json.loads(l); per.setdefault(x["_kal"], []).append(x)
    for v in per.values(): v.sort(key=lambda x: -x["issueDate"])
    c = []
    for i in range(max(len(v) for v in per.values())):
        for k in sorted(per, key=rank.get):
            if i < len(per[k]): c.append(per[k][i])
    os.makedirs(f"{B}/pdf", exist_ok=True)
    log = open(f"{B}/fetch_log.jsonl", "a"); done = set()
    for l in open(f"{B}/fetch_log.jsonl"):
        done.add(json.loads(l)["ada"])
    tot = sum(os.path.getsize(f"{B}/pdf/{f}") for f in os.listdir(f"{B}/pdf")); n = len(done)
    for x in c:
        if n >= cap_n or tot >= cap_bytes: print("cap reached", n, tot); break
        if x["ada"] in done: continue
        if not disk_ok(): print("DISK < 30G, stopping"); break
        u = f"{API}/decisions/{quote(x['ada'])}/document"
        rec = {"ada": x["ada"], "url": u}
        try:
            data, meta = P.get(u, timeout=(20, 180), cache=False, allow_redirects=False)
            fn = f"{B}/pdf/{x['ada']}.pdf"; open(fn, "wb").write(data)
            rec.update(bytes=len(data), ctype=meta["ctype"], retrieved_at=meta["retrieved_at"], ok=True)
            tot += len(data)
        except Exception as e:
            rec.update(ok=False, error=str(e)[:300])
        n += 1; log.write(json.dumps(rec, ensure_ascii=False) + "\n"); log.flush()
        if n % 100 == 0: print("fetched", n, round(tot / 2**20), "MiB", flush=True)
    print("done", n, tot)

if __name__ == "__main__":
    {"discover": discover, "classify": classify, "fetch": fetch}[sys.argv[1]]()
