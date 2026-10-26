"""France tranche 2 — probe B: earliest délibération year + overlaps."""
import json
import sys
from pathlib import Path

HF = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
sys.path.insert(0, str(HF / "fr_pilot" / "scripts"))
import fr_build as B  # noqa: E402

OUT = HF / "fr_tranche2"
SCR = OUT / "scratch"
fx = B.Fetcher()

per_year = {}
extra = []
for year in range(2009, 1999, -1):
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
    extra.extend(docs)
    print(year, "sessions:", len(sessions), "docs:", len(docs), flush=True)
    if not docs:
        break
(SCR / "pre2010_probe.json").write_text(
    json.dumps({"per_year": per_year, "docs": extra}, ensure_ascii=False, indent=1),
    encoding="utf-8")

# overlap vs tranche-1 published set
t1 = json.loads((HF / "fr_tranche1" / "besancon_doc_meta.json").read_text(encoding="utf-8"))
t1_ids = {d["doc_id"] for d in t1}
t1_urls = {d["url"] for d in t1}
pre = json.loads((SCR / "pre2024_corpus.json").read_text(encoding="utf-8"))
pre_docs = pre["docs"] + extra
pre_ids = {d["url"].rsplit("/", 1)[-1].rsplit(".", 1)[0].lower() for d in pre_docs}
pre_urls = {d["url"] for d in pre_docs}
print("t1 ids:", len(t1_ids), "pre ids:", len(pre_ids),
      "id overlap:", len(t1_ids & pre_ids), "url overlap:", len(t1_urls & pre_urls))
# sample of early doc ids / urls
for d in pre_docs[:3] + pre_docs[-3:]:
    print(d["date"], d["url"])
print("PROBE B DONE")
