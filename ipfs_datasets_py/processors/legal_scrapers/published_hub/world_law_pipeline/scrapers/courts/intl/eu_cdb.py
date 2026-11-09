"""European Court Database (e-Justice CDB) open API (POST https://webgate.ec.europa.eu/cdb/search, documented at data.europa.eu 'european-court-database-api').
Enumerates competent courts per Member State by unioning name-letter, court-type and postal-prefix queries. Raw -> data/ref/cdb/<CC>.json"""
import sys, json, os, time, urllib.request
ROOT = "/workspace/world_courts"
EU = "AT BE BG HR CY CZ DK EE FI FR DE EL HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()
def q(body, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request("https://webgate.ec.europa.eu/cdb/search", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "world_courts/0.1 (research)"})
            return json.loads(urllib.request.urlopen(r, timeout=90).read())
        except Exception as e:
            time.sleep(3 * (i + 1)); err = e
    print("ERR", body, err, flush=True); return {}
for cc in (sys.argv[1:] or EU):
    out = f"{ROOT}/data/ref/cdb/{cc}.json"
    if os.path.exists(out): continue
    got = {}
    qs = [{"courtName": c} for c in "aeiouy"] + [{"courtType": str(t)} for t in range(0, 12)] + [{"courtPostalCode": str(d)} for d in range(10)]
    for extra in qs:
        d = q({"country": cc, **extra}); time.sleep(0.6)
        for b in d.get("competentBodies", []) or []: got[b["id"]] = b
    json.dump(list(got.values()), open(out, "w"), ensure_ascii=False)
    print(cc, len(got), flush=True)
