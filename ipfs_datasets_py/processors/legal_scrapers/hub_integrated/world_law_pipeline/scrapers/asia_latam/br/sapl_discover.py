#!/usr/bin/env python3
"""Discover SAPL (Interlegis) instances: candidate host sapl.<slug>.<uf>.leg.br for each IBGE municipality
(Wikidata P1585). One robots.txt GET per host, then (if allowed) GET /api/norma/normajuridica/?page_size=1.
Resumable: results appended to _sapl_hosts.jsonl (skips hosts already probed). 12 threads, distinct hosts."""
import csv, json, re, sys, unicodedata, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.rfc9309 import Robots
UA = "JusticeDAO-WorldLaw/1.0 (+https://github.com/endomorphosis/ipfs_datasets_py; municipal law research crawler; polite)"
H = Path(__file__).resolve().parent
UF = {"11":"ro","12":"ac","13":"am","14":"rr","15":"pa","16":"ap","17":"to","21":"ma","22":"pi","23":"ce","24":"rn","25":"pb","26":"pe","27":"al","28":"se","29":"ba","31":"mg","32":"es","33":"rj","35":"sp","41":"pr","42":"sc","43":"rs","50":"ms","51":"mt","52":"go","53":"df"}
def slug(n):
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", n)
OUT = H / "_sapl_hosts.jsonl"
done = set()
if OUT.exists():
    for l in OUT.open():
        try: done.add(json.loads(l)["host"])
        except Exception: pass
rows = {}
for r in csv.DictReader(open(H / "wd_P1585.csv")):
    c = r["code"].strip()
    if len(c) == 7 and c[:2] in UF:
        rows.setdefault(c, (r["item"].rsplit("/", 1)[1], r["itemLabel"]))
lock = threading.Lock()
def probe(code):
    qid, name = rows[code]
    host = f"sapl.{slug(name)}.{UF[code[:2]]}.leg.br"
    if host in done: return
    rec = {"host": host, "ibge": code, "qid": qid, "name": name}
    s = requests.Session(); s.headers["User-Agent"] = UA
    try:
        r = s.get(f"https://{host}/robots.txt", timeout=20, allow_redirects=False)
        rec["robots_status"] = r.status_code
        if r.status_code >= 500: rec["robots"] = "unreachable_5xx"
        elif 300 <= r.status_code < 400: rec["robots"] = "redirect"; rec["loc"] = r.headers.get("Location")
        else:
            rb = Robots(r.text) if r.status_code == 200 and "<html" not in r.text[:500].lower() else Robots(allow_all=True)
            api = f"https://{host}/api/norma/normajuridica/?page_size=1"
            if not rb.can_fetch(UA, api): rec["robots"] = "disallow"
            else:
                rec["robots"] = "allow"; rec["crawl_delay"] = rb.crawl_delay(UA)
                import time; time.sleep(max(1.0, float(rec['crawl_delay'] or 0)))
                a = s.get(api, timeout=30, allow_redirects=False)
                rec["api_status"] = a.status_code
                if a.status_code == 200 and a.headers.get("content-type", "").startswith("application/json"):
                    j = a.json(); rec["count"] = j.get("pagination", {}).get("total_entries", j.get("count"))
    except requests.RequestException as e:
        rec["robots"] = "unreachable"; rec["err"] = type(e).__name__
    with lock:
        with OUT.open("a") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
with ThreadPoolExecutor(48) as ex: list(ex.map(probe, sorted(rows)))
print("done", flush=True)
