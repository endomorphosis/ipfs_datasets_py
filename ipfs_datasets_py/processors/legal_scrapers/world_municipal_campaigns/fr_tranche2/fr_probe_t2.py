"""France tranche 2 — probes.

A) Enumerate getConseilsMunicipaux for pre-2024 years (2023 -> 2010)
   to find the service's earliest year and the archive size.
B) Arrêtés: confirm robots posture on data.grandbesancon.fr +
   datasets.grandbesancon.fr, fetch the actesVilleDeBesancon fiche
   page (patient timeout), and try candidate besanconfr.php method
   names for the actes service.
"""
import json
import re
import sys
from pathlib import Path

HF = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
sys.path.insert(0, str(HF / "fr_pilot" / "scripts"))
import fr_build as B  # noqa: E402

OUT = HF / "fr_tranche2"
SCR = OUT / "scratch"
SCR.mkdir(parents=True, exist_ok=True)
fx = B.Fetcher()

# --- A: pre-2024 enumeration -------------------------------------------
per_year = {}
all_docs = []
for year in range(2023, 2009, -1):
    api = ("https://datasets.grandbesancon.fr/besanconfr.php"
           f"?method=getConseilsMunicipaux&year={year}&output=json")
    try:
        sessions = fx.get_json(api)
    except Exception as e:  # noqa: BLE001
        per_year[year] = f"failed: {type(e).__name__}: {str(e)[:100]}"
        print(year, per_year[year], flush=True)
        continue
    (SCR / f"besancon_{year}.json").write_text(
        json.dumps(sessions, ensure_ascii=False), encoding="utf-8")
    docs = []
    for sess in sessions:
        for d in sess.get("deliberations", []):
            if d.get("urlPdf"):
                docs.append({"title": (d.get("titre") or "").strip(),
                             "url": d["urlPdf"],
                             "date": (d.get("date") or sess.get("date") or "")[:10],
                             "session": sess.get("titre", "")})
    per_year[year] = len(docs)
    all_docs.extend(docs)
    print(year, "sessions:", len(sessions), "docs:", len(docs), flush=True)
seen, uniq = set(), []
for d in all_docs:
    if d["url"] not in seen:
        seen.add(d["url"])
        uniq.append(d)
(SCR / "pre2024_corpus.json").write_text(
    json.dumps({"per_year": per_year, "total_raw": len(all_docs),
                "total_unique": len(uniq), "docs": uniq},
               ensure_ascii=False, indent=1), encoding="utf-8")
print("pre-2024 unique docs:", len(uniq), flush=True)

# --- B: arrêtés service -------------------------------------------------
print("--- arrêtés probe ---", flush=True)
for host in ("https://data.grandbesancon.fr/robots.txt",
             "https://datasets.grandbesancon.fr/robots.txt"):
    try:
        body = fx.get(host).decode("utf-8", "replace")
        print(host, "->", repr(body[:300]), flush=True)
    except Exception as e:  # noqa: BLE001
        print(host, "fetch:", type(e).__name__, str(e)[:120], flush=True)

fiche_url = "https://data.grandbesancon.fr/opendata/dataset/actesVilleDeBesancon"
try:
    html = fx.get(fiche_url, timeout=180).decode("utf-8", "replace")
    (SCR / "gb_page_actesVilleDeBesancon.html").write_text(html, encoding="utf-8")
    print("fiche bytes:", len(html), flush=True)
    methods = sorted(set(re.findall(r"besanconfr\.php\?method=([A-Za-z]+)", html)))
    print("methods in fiche:", methods, flush=True)
    for m in sorted(set(re.findall(r"besanconfr\.php\?method=[^\"' ]+", html)))[:12]:
        print("  ", m, flush=True)
    files = sorted(set(re.findall(r"https://datasets\.grandbesancon\.fr/fichiers/[^\"' ]+", html)))
    print("fichiers links:", len(files), flush=True)
    for f in files[:10]:
        print("  ", f, flush=True)
except Exception as e:  # noqa: BLE001
    print("fiche fetch failed:", type(e).__name__, str(e)[:200], flush=True)
print("PROBE DONE", flush=True)
