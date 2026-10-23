"""Fill the articles cache for one gemeente besluit-by-besluit with short
timeouts (batch queries 504 on Lanaken's article graph). Besluiten whose
article query keeps timing out are cached as [] — the harvest then falls
back to splitting their (already cached) besluit-level prov:value."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sparql_client as sc  # noqa: E402
import requests  # noqa: E402

CAMP = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files/be_campaign"
nis = sys.argv[1]
inv = json.load(open(CAMP / "inventory.json"))
cache_path = CAMP / "cache" / f"{nis}_articles.json"
cache = json.load(open(cache_path)) if cache_path.exists() else {}
all_uris = [r["uri"] for r in inv["per_gemeente"][nis]["inline"]] + \
           [r["uri"] for r in inv["per_gemeente"][nis]["stub"]]
todo = [u for u in all_uris if u not in cache]
print(f"{nis}: {len(todo)} besluiten to fill", flush=True)

s = requests.Session()
s.headers.update(sc.UA)
failed = []
for i, u in enumerate(todo):
    q = sc.PFX + f"""SELECT ?number ?value WHERE {{
      <{u}> eli:has_part ?a . ?a a besluit:Artikel ; prov:value ?value .
      OPTIONAL {{ ?a eli:number ?number }} }}"""
    arts, ok = [], False
    for attempt in range(2):
        try:
            r = s.post(sc.EP, data={"query": q, "format": "application/sparql-results+json"}, timeout=75)
            if r.status_code == 200:
                for row in sc.bindings_map(r.json()["results"]["bindings"]):
                    arts.append({"number": row.get("number", ""), "value": row.get("value", "")})
                ok = True
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(3)
    if not ok:
        failed.append(u)  # left UNCACHED so a later pass can retry
    else:
        cache[u] = arts
        cache_path.write_text(json.dumps(cache, ensure_ascii=False))
    if (i + 1) % 25 == 0 or not ok:
        print(f"  {i + 1}/{len(todo)} filled (failed so far: {len(failed)})", flush=True)
    time.sleep(0.7)
print(f"done: {len(cache)} cached; per-besluit failures left uncached for retry: {len(failed)}")
for u in failed:
    print("  RETRY-LATER:", u)
