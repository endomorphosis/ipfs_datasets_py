"""Ingest Chief-of-Staff US seed court links (inbox/from_cos.jsonl): polite live fetch (robots + Crawl-delay, min 2 s/host),
skip 403 / Cloudflare challenge / JS-only shells (no bypass, no archive), drop noise pages, extract official names+addresses,
Census batch geocode, incremental merge into us_courthouses.jsonl (same dedupe as us_merge_courthouses), keep gnis_id.
usage: us_cos_ingest.py fetch ST,ST | merge   (fetch writes data/us/cos/<ST>.jsonl + blockers)"""
import sys, re, json, time, datetime, hashlib, urllib.request, urllib.parse, urllib.robotparser, threading
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, "/workspace/world_courts/scrapers/courts")
import us_directory_extract as de
from robots_policy import UA
D = "/workspace/world_courts/data/us/"; SEED = "/workspace/world_courts/inbox/from_cos.jsonl"
NOISE = re.compile(r"pay(ment|ments|online|-?fine|-?ticket)?\b|epay|drug|treatment|veteran|recovery|jury|docket|search|records-?search|e-?fil|calendar|employ|job|career|news|faq|bid|rfp|minutes|agenda|probation|child-?support|mental-?health|dui|sobriety", re.I)
CF = re.compile(r"Just a moment\.\.\.|cf-chl|challenge-platform|Attention Required! \| Cloudflare|_Incapsula_|Access Denied", re.I)
_rp = {}; _lk = {}; _last = {}
def robots(u):
    p = urllib.parse.urlsplit(u); base = f"{p.scheme}://{p.netloc}"
    if base not in _rp:
        try:
            t = urllib.request.urlopen(urllib.request.Request(base + "/robots.txt", headers={"User-Agent": UA}), timeout=20).read().decode("utf-8", "replace")
            rp = urllib.robotparser.RobotFileParser(); rp.parse(t.splitlines()); _rp[base] = ("ok", rp)
        except urllib.error.HTTPError as e: _rp[base] = ("absent", None) if 400 <= e.code < 500 else ("unreachable", None)
        except Exception: _rp[base] = ("unreachable", None)
    s, rp = _rp[base]
    import robots_policy as _RP
    if _RP.optout(u): return "robots_disallowed", 10.0
    if s != "ok": return ("robots_absent_allowed" if s == "absent" else "robots_unreachable"), 10.0
    cd = rp.crawl_delay(UA) or rp.crawl_delay("*") or 10.0
    ok = rp.can_fetch(UA, u)
    return ("robots_allowed" if ok else ("robots_disallowed_ignored_per_owner" if _RP.IGNORE_ROBOTS else "robots_disallowed")), max(2.0, float(cd))
def fetch(u):
    host = urllib.parse.urlsplit(u).netloc; lk = _lk.setdefault(host, threading.Lock())
    with lk:
        pol, delay = robots(u)
        if pol == "robots_disallowed": return None, pol, "robots_disallowed"
        w = _last.get(host, 0) + delay - time.time()
        if w > 0: time.sleep(w)
        try:
            r = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=30); h = r.read(4_000_000).decode("utf-8", "replace"); err = None
        except urllib.error.HTTPError as e: h, err = None, f"http_{e.code}"
        except Exception as e: h, err = None, "error:" + type(e).__name__
        _last[host] = time.time()
    if h and CF.search(h[:20000]): return None, pol, "challenge"
    if h and len(de.totext(h).strip()) < 300: return None, pol, "js_only_or_empty"
    return h, pol, err
BADN = re.compile(r"(?i)\b(judge|hon\.?|welcome|hours|not|weapons|address|advice|phone|fax|email|located|please|click|map|directions|mail|contact|our|the court does|visit|website|information|divisions|links|services|home|online|forms|page|menu|department)\b")
def goodname(n):
    n = re.sub(r"\s+", " ", (n or "").split(":")[0]).strip(" *|,:-.")
    if not (6 <= len(n) <= 70) or BADN.search(n) or n.isupper() and len(n) > 40: return None
    if not re.search(r"(?i)(court|courthouse|justice center|judicial (center|complex|building)|probate|magistrate)", n): return None
    if not re.match(r"[A-Z0-9]", n): return None
    return n
def one(s):
    h, pol, err = fetch(s["url"])
    if not h: return s, [], err or "empty", pol
    de.STNAME[s["state"]] = s["state"]; t = de.totext(h); out = []
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", h); title = None
    if m:
        for part in re.split(r"\s[|\-\u2013\u2014:]\s", de.html.unescape(m.group(1))):
            title = title or goodname(part)
    for a in de.extract(t, s["state"]):
        if not a["name"] or re.match(r"(?i)p\.?\s*o\.?\s*box", a["street"]) or not re.match(r"\d+\s+\S", a["street"]): continue
        nm = goodname(a["name"]) or title
        if not nm: continue
        out.append({"name": nm, "street": a["street"].split("\n")[-1].strip(" ,"), "city": a["city"], "postcode": a["postcode"]})
    return s, out, None if out else "no_address_found", pol
def fetch_states(states):
    seeds = [json.loads(l) for l in open(SEED)]; seeds = [s for s in seeds if s["kind"] == "court" and s["state"] in states]
    keep = [s for s in seeds if not NOISE.search(urllib.parse.urlsplit(s["url"]).path + "?" + urllib.parse.urlsplit(s["url"]).query)]
    print("seeds", len(seeds), "after noise filter", len(keep), flush=True)
    now = datetime.datetime.now(datetime.UTC).isoformat()
    with ThreadPoolExecutor(16) as ex: res = list(ex.map(one, keep))
    for st in states:
        rows, blk = [], []
        for s, out, err, pol in res:
            if s["state"] != st: continue
            if err and not out: blk.append({"url": s["url"], "county_or_place": s["county_or_place"], "reason": err}); continue
            for a in out:
                rows.append({"court_id": None, "name": a["name"], "level": None, "court_system": "state", "country_code": "US", "subdivision": "US-" + st, "jurisdiction": None,
                    "parent_court_id": None, "address": {"street": a["street"], "city": a["city"], "postcode": a["postcode"], "region": st, "country": "US"}, "geo": None,
                    "place_ids": [], "gnis_id": s["gnis_id"], "seed_county_or_place": s["county_or_place"], "source_url": s["url"], "source_kind": "official",
                    "site_policy": pol, "retrieved_at": now, "needs_review": True, "seed": "chief_of_staff_inbox"})
        u = {}
        for r in rows: u.setdefault((r["address"]["street"].lower(), r["address"]["postcode"]), r)
        with open(f"{D}cos/{st}.jsonl", "w") as f:
            for r in u.values(): f.write(json.dumps(r) + "\n")
        with open(f"{D}cos/{st}.blockers.jsonl", "w") as f:
            for b in blk: f.write(json.dumps(b) + "\n")
        print(st, "rows", len(u), "blocked/empty", len(blk), flush=True)
def merge(states):
    import us_merge_courthouses as M, us_place_match as pm
    allr = [json.loads(l) for l in open(D + "us_courthouses.jsonl")]
    dr = [json.loads(l) for st in states for l in open(f"{D}cos/{st}.jsonl")]
    g = M.batch_geocode(dr) if dr else {}
    for i, r in enumerate(dr):
        if i in g: r["geo"] = {"lat": g[i]["lat"], "lon": g[i]["lon"]}; r["county_fips"] = g[i]["county_fips"]
    grid = {}
    for k, r in enumerate(allr):
        if r.get("geo"): grid.setdefault((r["subdivision"], round(r["geo"]["lat"], 2), round(r["geo"]["lon"], 2)), []).append(k)
    ids = {r["court_id"] for r in allr}; geo, nm = pm.load_gm(); stat = {}
    for r in dr:
        st = r["subdivision"][3:]; c = stat.setdefault(st, {"extracted": 0, "geocoded": 0, "merged": 0, "added": 0}); c["extracted"] += 1
        src = {"source_url": r["source_url"], "site_policy": r["site_policy"], "source_kind": "official", "name": r["name"], "address": r["address"], "gnis_id": r.get("gnis_id")}
        if not r["geo"]: continue  # ungeocoded rows are not merged (cannot dedupe safely)
        c["geocoded"] += 1; best = None; la, lo = round(r["geo"]["lat"], 2), round(r["geo"]["lon"], 2)
        for dla in (-0.01, 0, 0.01):
            for dlo in (-0.01, 0, 0.01):
                for k in grid.get((r["subdivision"], round(la + dla, 2), round(lo + dlo, 2)), []):
                    d = M.hav(r["geo"], allr[k]["geo"])
                    if d < 150 or (d < 600 and M.toks(r["name"]) & M.toks(allr[k].get("name"))):
                        if best is None or d < best[0]: best = (d, k)
        if best:
            o = allr[best[1]]; S = o.setdefault("sources", [])
            if not any(x.get("source_url") == r["source_url"] and x.get("name") == r["name"] for x in S): S.append(src)
            o["official_name"] = o.get("official_name") or r["name"]; o["gnis_id"] = o.get("gnis_id") or r.get("gnis_id")
            if not (o.get("address") or {}).get("street"): o["address"] = r["address"]
            if r.get("parent_court_id") and not o.get("parent_court_id"): o["parent_court_id"] = r["parent_court_id"]; o["court_system"] = r["court_system"]; o["level"] = o.get("level") or r.get("level")
            src["parent_court_id"] = r.get("parent_court_id")
            c["merged"] += 1
        else:
            r["court_id"] = "usdir:" + hashlib.sha1((r["subdivision"] + r["address"]["street"] + r["address"]["postcode"]).lower().encode()).hexdigest()[:12]
            if r["court_id"] in ids: continue
            p = nm.get((pm.norm(r["address"]["city"]), st)); pl = ([p] if p else []) + ([geo[r["county_fips"]]] if r.get("county_fips") in geo else [])
            if r.get("gnis_id") and "gnis:" + r["gnis_id"] not in pl: pl.append("gnis:" + r["gnis_id"])
            r["place_ids"] = pl; r["place_match_method"] = "name+county_fips+cos_gnis"; r["sources"] = [src]
            ids.add(r["court_id"]); allr.append(r); grid.setdefault((r["subdivision"], la, lo), []).append(len(allr) - 1); c["added"] += 1
    with open(D + "us_courthouses.jsonl", "w") as f:
        for r in allr: f.write(json.dumps(r) + "\n")
    print(json.dumps(stat), "total", len(allr))
if __name__ == "__main__":
    if sys.argv[1] == "fetch": fetch_states(sys.argv[2].split(","))
    else: merge(sys.argv[2].split(","))
