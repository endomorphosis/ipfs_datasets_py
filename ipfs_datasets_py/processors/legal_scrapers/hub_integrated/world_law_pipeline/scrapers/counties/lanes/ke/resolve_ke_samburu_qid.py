#!/usr/bin/env python3
"""Wikidata QID check for Samburu County (batch 2 of ipfs_kenya_municipal_laws) via the robots-allowed Special:EntityData
route ONLY (https://www.wikidata.org/wiki/Special:EntityData/<QID>.json); no search API (wbsearchentities, Special:Search,
the query service). The candidate QID comes from the bundled county seed list (seeds/KE.jsonl, municipality ke-025); the
item is fetched once and accepted only if its English label is 'Samburu County', it is an instance of (P31) the seed's
wikidata_class (county of Kenya) and its country (P17) is Kenya (Q114). robots_guard on every send (robots.txt read once), hard pacer
>= max(5 s, Crawl-Delay) per host across runs (KE_QID_PACING_LOGS), TLS verified, one request in flight. Writes
$MUNI_STAGE/qid_samburu.json. Never uploads."""
import glob, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

STAGE = Path(os.environ.get("MUNI_STAGE", "/dev/shm/muni_africa/ke/samburu"))
os.environ.setdefault("LEGAL_CORPORA_ROOT", str(STAGE / "root"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import robots_guard as rg  # noqa: E402
import requests  # noqa: E402

rg.set_country("ke")
HOST = "www.wikidata.org"
MAXF = 2
LOG = STAGE / "requests.jsonl"
STATE = {"last": None, "n": 0}


def iso_ms(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


PACING_LOGS = os.environ.get("KE_QID_PACING_LOGS", f"{LOG} /dev/shm/muni_africa/*/*/requests.jsonl /dev/shm/muni_africa/*/requests.jsonl").split()


def last_send():
    best = None
    for p in sorted({x for g in PACING_LOGS for x in glob.glob(g)}):
        for l in open(p):
            try:
                d = json.loads(l)
            except ValueError:
                continue
            if (urlparse(d.get("url") or "").hostname or "") == HOST:
                st = d.get("sent_at") or []
                for x in ([st] if isinstance(st, str) else st):
                    t = datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp() + 0.001
                    best = t if best is None else max(best, t)
    return best


def pace(gap):
    last = STATE["last"] if STATE["last"] is not None else last_send()
    if last is not None:
        w = last + gap - time.time()
        if w > 0:
            time.sleep(w + 0.05)
        if time.time() - last < gap:
            raise SystemExit(f"PacingError: {time.time() - last:.3f} s < {gap} s; not sent")
    t = time.time(); STATE["last"] = t
    return t


def cd_gap():
    st = rg._cache.get("https://" + HOST)
    return max(5.0, float(st.crawl_delay or 0) if st else 0.0)


def robots_fetch(url):
    t = pace(5.0)
    r = requests.get(url, timeout=(15, 30), verify=rg.ca_verify_for(url), allow_redirects=False,
                     headers={"User-Agent": rg.ROBOTS_UA, "Accept": "text/plain,*/*"})
    with open(LOG, "a") as fh:
        fh.write(json.dumps({"url": url, "kind": "robots_txt", "status": r.status_code, "sent_at": [iso_ms(t)]}) + "\n")
    if r.status_code in (403, 429, 503) or r.headers.get("cf-mitigated"):
        raise SystemExit(f"HARD STOP robots {r.status_code}")
    return r.status_code, r.text, ""


rg._robots_fetcher = robots_fetch


def entity(qid):
    if STATE["n"] >= MAXF:
        raise SystemExit("EntityData fetch cap reached")
    url = f"https://{HOST}/wiki/Special:EntityData/{qid}.json"
    d = rg.check(url)
    if not d.allowed:
        raise SystemExit(f"robots: {d.reason} {url}")
    t = pace(cd_gap())
    STATE["n"] += 1
    r = requests.get(url, timeout=(15, 60), verify=rg.ca_verify_for(url), allow_redirects=False, headers={"User-Agent": rg.ROBOTS_UA})
    with open(LOG, "a") as fh:
        fh.write(json.dumps({"url": url, "kind": "wikidata_entitydata", "status": r.status_code, "sent_at": [iso_ms(t)],
                             "bytes": len(r.content), "robots": d.reason, "crawl_delay": d.crawl_delay}) + "\n")
    if r.status_code in (403, 429, 503) or r.headers.get("cf-mitigated"):
        raise SystemExit(f"HARD STOP {r.status_code} at {url}")
    if r.status_code in (301, 302, 303, 307, 308):   # redirected (merged) item: follow by QID through the same gate
        tgt = r.headers.get("Location", "").rstrip("/").split("/")[-1].replace(".json", "")
        return entity(tgt)
    r.raise_for_status()
    e = r.json()["entities"]
    return next(iter(e.values()))


def claims(e, p):
    out = []
    for c in e.get("claims", {}).get(p, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and v.get("id"):
            out.append(v["id"])
    return out


def label(e):
    return (e.get("labels", {}).get("en") or {}).get("value", "")


def main():
    seeds = Path(os.environ.get("MUNI_SEEDS_KE", str(Path(__file__).resolve().parent / "seeds" / "KE.jsonl")))
    seed = next(json.loads(l) for l in open(seeds) if '"Samburu' in l)
    q = seed.get("qid") or seed.get("wikidata_qid")
    e = entity(q)
    p31, p17 = claims(e, "P31"), claims(e, "P17")
    cls = seed.get("wikidata_class") or "Q211748"
    ok = label(e) == "Samburu County" and cls in p31 and "Q114" in p17
    res = {"route": "https://www.wikidata.org/wiki/Special:EntityData/<QID>.json (robots-allowed); no search API used",
           "seed_qid": q, "seed_file": seeds.name, "fetched_qid": e["id"], "label_en": label(e), "P31": p31, "P17": p17,
           "P131": claims(e, "P131"), "class_required": cls, "accepted": ok, "qid": e["id"] if ok else None, "at": iso_ms(time.time())}
    (STAGE / "qid_samburu.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
