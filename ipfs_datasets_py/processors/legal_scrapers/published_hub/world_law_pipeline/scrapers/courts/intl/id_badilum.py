"""ID Pengadilan Tinggi + Pengadilan Negeri court_body rows from Ditjen Badilum (Mahkamah Agung) official PDF
'Daftar satuan kerja yang sudah mendapatkan ijin register elektronik' (data per 8 Nov 2024). Dedup by normalized name."""
import json, sys, re, datetime, subprocess, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
OUT = f"{ROOT}/data/id/id_courthouses.jsonl"; PDF = f"{ROOT}/rules/raw/id/badilum_register_elektronik_2024.pdf"
SRC = "https://badilum.mahkamahagung.go.id/attachments/article/3911/DAFTAR%20SATUAN%20KERJA%20YANG%20SUDAH%20MENDAPATKAN%20IJIN%20REGISTER%20ELEKTRONIK.pdf"
sha = hashlib.sha256(open(PDF, "rb").read()).hexdigest()
txt = subprocess.run(["pdftotext", "-layout", PDF, "-"], capture_output=True, text=True).stdout
def key(n):
    n = norm(n); n = re.sub(r"\b(kelas|klas|kls)\s*i+[ab]?\b", "", n); n = re.sub(r"\bkab(upaten)?\b|\bkota\b", "", n)
    return re.sub(r"\s+", " ", n).strip()
rows = [json.loads(l) for l in open(OUT)]; seen = {key(r["name"]) for r in rows}; ids = {r["court_id"] for r in rows}
pts, pns = [], []
for l in txt.splitlines():
    m = re.match(r"\s*\d+\s+(Pengadilan Tinggi .+?)\s*$", l)
    if m: pts.append(m.group(1)); continue
    m = re.match(r"\s*\d+\s+PT\s+(.+?)\s{2,}(Pengadilan Negeri .+?)\s*$", l)
    if m: pns.append((m.group(1).title(), m.group(2)))
now = datetime.datetime.now(datetime.UTC).isoformat()
def slug(s): return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")
sc = next((r["court_id"] for r in rows if r["name"] == "Mahkamah Agung"), None)
new = []
def mk(name, level, parent, region):
    cid = f"id-{slug(name)}"
    if key(name) in seen or cid in ids: return
    seen.add(key(name)); ids.add(cid)
    loc = re.sub(r"^Pengadilan (Tinggi|Negeri)\s+", "", name)
    new.append({"court_id": cid, "record_type": "court_body", "name": name, "name_local": name, "level": level,
      "court_system": "national", "country_code": "ID", "subdivision": "ID", "jurisdiction": loc, "parent_court_id": parent,
      "address": {"street": None, "city": None, "postcode": None, "region": region, "country": "Indonesia"}, "geo": {"lat": None, "lon": None},
      "phone": None, "website": None, "wikidata": None, "place_ids": rmatch([loc], "ID"), "source_url": SRC, "source_kind": "official",
      "site_policy": "robots_allowed", "retrieved_at": now, "license": "public-sector-information", "source_sha256": sha,
      "sources": [{"source_url": SRC, "site_policy": "robots_allowed", "source_kind": "official"}],
      "record_note": "Badilum list of courts with e-register permit (8 Nov 2024); court list may omit courts without permit"})
for p in pts: mk(p, "appellate", sc, None)
for pt, pn in pns: mk(pn, "trial_general", f"id-{slug('Pengadilan Tinggi ' + pt)}", pt)
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("parsed PT", len(pts), "PN", len(pns), "added", len(new), "placed", sum(bool(r["place_ids"]) for r in new))
