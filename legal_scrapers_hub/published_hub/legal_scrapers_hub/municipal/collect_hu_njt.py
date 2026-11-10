"""Hungarian local-government decrees fetched directly from the official Nemzeti Jogszabálytár, njt.jog.gov.hu (the successor of
or.njt.hu; old or.njt.hu /eli/ URLs redirect there). Polite by design: robots.txt is read first and obeyed (only /jogszabaly/<year>-<no>-SP-5Y<code>
pages are requested, which robots.txt allows; /search/* is disallowed and never used), one connection, one request at a time, at least
DELAY seconds (default 1.2 s, or the robots crawl-delay if larger) between requests, a clear User-Agent, backoff on 429/5xx.
The site has no decree listing that robots.txt allows, so decrees are enumerated by URL pattern per issuer (SP code), year and number:
  tier 1  cities with county rights + Budapest capital, years 2023-2026, numbers 1.. until 3 misses in a row past the highest known number
  tier 2  Budapest districts, years 2024-2026, same rule
  tier 3  numbers missing from the pack below the highest known number of an (issuer, year), newest year first ("gaps")
Decrees already in the pack or captured by Common Crawl in the SP form are skipped (gap-first). Output: HU_BUILD/njt_pages.jsonl.gz (resumable).
  python collect_hu_njt.py PLAN.json [max_requests]
PLAN.json: {"sp_of_issuer": {issuer: sp}, "have": [[issuer, year, no], ...], "tier1": [issuer...], "tier2": [...], "gaps": [[issuer, year, no], ...]}"""
import os, sys, json, gzip, time, re, signal, datetime, urllib.robotparser, collections
import requests
B = os.environ.get("HU_BUILD", "hu_build"); HOST = "https://njt.jog.gov.hu"
UA = "EndomorphosisWorldLaws-municipal/1.0 (research corpus of Hungarian municipal decrees; polite single-connection crawler, 1 req/s max)"
DELAY = float(os.environ.get("NJT_DELAY", "3.0"))
# the site answers a too-fast client with HTTP 200 and 'Túl sok lekérdezés, adott idő alatt!' (too many requests in a given time) instead of the
# decree: such a page is not stored as done; the crawler waits 60 s, raises its delay by 1 s (up to 30 s) and asks again. At 1.2-1.55 s per request
# the site allowed bursts of about 11 requests and then about 11 per 100 s (13:04-13:14 PT 2026-10-17), so this run used NJT_DELAY=9 (no throttling).
THROTTLE = "Túl sok lekérdezés"
STOP = False
def _stop(sig, frm):
    global STOP; STOP = True; print("signal", sig, "stopping after the current request", flush=True)
signal.signal(signal.SIGTERM, _stop); signal.signal(signal.SIGINT, _stop)
def main(plan_p, max_req=10**9):
    plan = json.load(open(plan_p)); sp = plan["sp_of_issuer"]
    S = requests.Session(); S.headers["User-Agent"] = UA
    rp = urllib.robotparser.RobotFileParser(); rtxt = S.get(HOST + "/robots.txt", timeout=30).text; rp.parse(rtxt.splitlines())
    cd = rp.crawl_delay(UA) or rp.crawl_delay("*") or 0; delay = max(DELAY, float(cd)); print("robots crawl-delay", cd, "-> delay", delay, flush=True)
    def allowed(path): return not path.startswith("/search/") and rp.can_fetch(UA, HOST + path) is not False
    out_p = f"{B}/njt_pages.jsonl.gz"; done = {}
    import fcntl                                   # one writer only: a second instance would interleave gzip members
    lockf = open(out_p + ".lock", "w")
    try: fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: raise SystemExit("another collect_hu_njt.py is writing " + out_p)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from collect_hu_cc import read_jsonl_gz
    if os.path.exists(out_p):
        if True:
            for r in read_jsonl_gz(out_p):
                if r.get("http") == 404 or (r.get("http") == 200 and THROTTLE not in r.get("html", "")): done[tuple(r["key"])] = r["http"]
    have = {tuple(map(str, k)) for k in plan["have"]}
    st = collections.Counter(); n_req = [0]; last = [0.0]; t0 = time.time(); dl = [delay]
    out = gzip.open(out_p, "at", encoding="utf-8")
    def get(iss, y, n):
        path = f"/jogszabaly/{y}-{n}-SP-5Y{sp[iss]}"
        if not allowed(path): st["robots_disallowed"] += 1; return None
        for att in range(6):
            if STOP: return None
            w = dl[0] - (time.time() - last[0])
            if w > 0: time.sleep(w)
            try: r = S.get(HOST + path, timeout=60, allow_redirects=False)
            except requests.RequestException as e: last[0] = time.time(); n_req[0] += 1; st["net_error"] += 1; time.sleep(10 * (att + 1)); continue
            last[0] = time.time(); n_req[0] += 1
            if r.status_code in (429, 500, 502, 503, 504):
                ra = r.headers.get("Retry-After"); time.sleep(min(300, int(ra)) if ra and ra.isdigit() else 30 * (att + 1)); st[f"http_{r.status_code}"] += 1; continue
            if r.status_code == 200 and THROTTLE in r.text:
                st["throttled"] += 1; dl[0] = min(30.0, dl[0] + 1.0); print(time.strftime("%H:%M:%S"), "throttled; delay ->", dl[0], flush=True); [time.sleep(1) for _ in range(60) if not STOP]; continue
            rec = dict(key=[iss, y, n], url=HOST + path, http=r.status_code, fetched_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S"))
            if r.status_code == 200: rec["html"] = r.content.decode("utf-8", "replace")
            elif r.status_code in (301, 302): rec["location"] = r.headers.get("Location")
            out.write(json.dumps(rec, ensure_ascii=False) + "\n"); done[(iss, y, n)] = r.status_code; st[f"http_{r.status_code}"] += 1
            if n_req[0] % 25 == 0: out.flush()
            if n_req[0] % 100 == 0: print(time.strftime("%H:%M:%S"), n_req[0], dict(st), f"{(time.time()-t0)/max(1,n_req[0]):.2f}s/req delay {dl[0]}", flush=True)
            return r.status_code
        return None
    def run_open(issuers, years):
        for iss in issuers:
            if iss not in sp: st["no_sp_code"] += 1; continue
            for y in years:
                known = [int(k[2]) for k in have if k[0] == iss and k[1] == str(y)]; top = max(known or [0]); miss = 0; n = 0
                while n < 150 and not STOP and n_req[0] < max_req:
                    n += 1; k = (iss, str(y), str(n))
                    if k in have: miss = 0; continue
                    c = done.get(k) or get(*k)
                    if c == 200: miss = 0
                    elif c == 404: miss += 1
                    if n > max(top, 5) and miss >= 3: break
                if STOP or n_req[0] >= max_req: return
    run_open(plan["tier1"], [2026, 2025, 2024, 2023]); print("tier1 done", n_req[0], dict(st), flush=True)
    run_open(plan["tier2"], [2026, 2025, 2024]); print("tier2 done", n_req[0], dict(st), flush=True)
    for iss, y, n in plan["gaps"]:
        if STOP or n_req[0] >= max_req: break
        k = (str(iss), str(y), str(n))
        if k in have or k in done or iss not in sp: continue
        get(*k)
    out.close(); print("done", n_req[0], dict(st), f"{time.time()-t0:.0f}s", flush=True)
if __name__ == "__main__":
    os.makedirs(B, exist_ok=True); main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 10**9)
