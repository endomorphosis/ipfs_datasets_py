"""France tranche 2 — assemble the two harvest corpora.

A) Délibérations pre-2024 (1989–2023) from the per-year probe JSONs
   saved in scratch/ (besancon_<year>.json sessions + probe doc
   lists). Deduped by URL; asserted disjoint from the tranche-1
   published corpus (2024–2026).
B) Actes (arrêtés + décisions) from the actes.php XML listing
   (scratch/actes_bare.out). One record per acte.
"""
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

HF = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
OUT = HF / "fr_tranche2"
SCR = OUT / "scratch"


def docs_from_sessions(sessions):
    docs = []
    for sess in sessions:
        for d in sess.get("deliberations", []):
            if d.get("urlPdf"):
                docs.append({"title": (d.get("titre") or "").strip(),
                             "url": d["urlPdf"],
                             "date": (d.get("date") or sess.get("date") or "")[:10],
                             "session": sess.get("titre", "")})
    return docs


# --- A: délibérations, from the cached per-year session JSONs ----------
per_year, raw = {}, []
for year in range(1989, 2024):
    p = SCR / f"besancon_{year}.json"
    assert p.exists(), f"missing session cache for {year}"
    docs = docs_from_sessions(json.loads(p.read_text(encoding="utf-8")))
    per_year[year] = len(docs)
    raw.extend(docs)
seen, delib = set(), []
for d in raw:
    if d["url"] not in seen:
        seen.add(d["url"])
        delib.append(d)
delib.sort(key=lambda d: (d["date"], d["title"]))

def stem(url):
    return url.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()

ids = Counter(stem(d["url"]) for d in delib)
collisions = {k: v for k, v in ids.items() if v > 1}
print("delib raw:", len(raw), "unique-url:", len(delib),
      "unique ids:", len(ids), "id collisions:", len(collisions))
if collisions:
    print("collision sample:", list(collisions.items())[:5])

# doc_id assignment: bare stem when globally unique (pilot/tranche-1
# convention); colliding old-style stems (named by session day, reused
# across years) get "-<YYYYMMDD>" from the URL path's session-date
# directory. Assert global uniqueness at the end.
import re as _re
_t1_tmp = json.loads((HF / "fr_tranche1" / "besancon_corpus.json").read_text(encoding="utf-8"))
_universe = Counter(stem(d["url"]) for d in _t1_tmp["docs"])
_universe.update(ids)
_used = set()
for d in delib:
    s = stem(d["url"])
    if _universe[s] == 1:
        did = s
    else:
        m = _re.search(r"/(\d{8})/", d["url"])
        did = f"{s}-{m.group(1)}" if m else s
        base, k = did, 2
        while did in _used:
            did = f"{base}-{k}"
            k += 1
    assert did not in _used, did
    _used.add(did)
    d["doc_id"] = did
print("doc_ids assigned, unique:", len(_used))

t1 = json.loads((HF / "fr_tranche1" / "besancon_corpus.json").read_text(encoding="utf-8"))
t1_urls = {d["url"] for d in t1["docs"]}
t1_ids = {stem(u) for u in t1_urls}
print("overlap with tranche-1: urls", len(seen & t1_urls), "ids", len(set(ids) & t1_ids))
assert not (seen & t1_urls)
(OUT / "delib_pre2024_corpus.json").write_text(
    json.dumps({"per_year": per_year, "total": len(delib), "docs": delib},
               ensure_ascii=False, indent=1), encoding="utf-8")
print("delib per_year:", per_year)

# --- B: actes ------------------------------------------------------------
root = ET.fromstring((SCR / "actes_bare.out").read_bytes())
actes, seen_ids = [], set()
type_dist, year_dist = Counter(), Counter()
for a in root.findall(".//acte"):
    d = {ch.tag: (ch.text or "") for ch in a}
    aid = a.get("id")
    assert aid and aid not in seen_ids, f"dup acte id {aid}"
    seen_ids.add(aid)
    type_dist[d.get("type", "")] += 1
    year_dist[a.get("year", "")] += 1
    actes.append({"acte_id": aid, "title": d.get("titre", "").strip(),
                  "domaine": d.get("domaine", ""), "type": d.get("type", ""),
                  "url": d.get("fichier", ""), "date_acte": d.get("dateActe", ""),
                  "date_publication": d.get("datePublication", ""),
                  "year": a.get("year", "")})
actes.sort(key=lambda d: (d["date_acte"], d["acte_id"]))
assert all(d["url"] for d in actes)
print("actes:", len(actes), "types:", dict(type_dist), "years:", dict(sorted(year_dist.items())))
delib_ids = set(ids)
acte_ids = {d["acte_id"].lower() for d in actes}
print("acte/delib id cross-collision:", len(acte_ids & delib_ids),
      "acte/t1 collision:", len(acte_ids & t1_ids))
(OUT / "actes_corpus.json").write_text(
    json.dumps({"total": len(actes), "types": dict(type_dist),
                "years": dict(sorted(year_dist.items())), "docs": actes},
               ensure_ascii=False, indent=1), encoding="utf-8")
print("CORPUS DONE")
