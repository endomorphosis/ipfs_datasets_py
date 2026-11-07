"""AR-M: Mendoza courts + judges (public name/title only; e-mails NOT stored) from jusmendoza.gob.ar 'Guía Judicial' department pages
(robots: Allow /, Crawl-delay 120 respected). One row per tribunal (name ends with -1CJ..-4CJ)."""
import json, sys, re, html, glob, os, datetime, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
RAW = f"{ROOT}/rules/raw/ar_mza"; CO = f"{ROOT}/data/ar/ar_courthouses.jsonl"; JO = f"{ROOT}/data/ar/ar_judges.jsonl"
rows = [json.loads(l) for l in open(CO)]; ids = {r["court_id"] for r in rows}; seen = {norm(r["name"]) for r in rows}
jids = {json.loads(l)["judge_id"] for l in open(JO)} if os.path.exists(JO) else set()
now = datetime.datetime.now(datetime.UTC).isoformat(); courts, judges = [], []
if "ar-m-scjm" not in ids:
    courts.append({"court_id": "ar-m-scjm", "record_type": "court_body", "name": "Suprema Corte de Justicia de Mendoza", "name_local": None, "level": "supreme", "court_system": "state",
      "country_code": "AR", "subdivision": "AR-M", "jurisdiction": "Provincia de Mendoza", "parent_court_id": None, "address": {"street": "Av. España 480", "city": "Mendoza", "postcode": None, "region": "Mendoza", "country": "Argentina"},
      "geo": {"lat": None, "lon": None}, "phone": None, "website": "https://jusmendoza.gob.ar/", "wikidata": None, "place_ids": rmatch(["Mendoza", "Capital"], "AR"),
      "source_url": "https://jusmendoza.gob.ar/guia-judicial/", "source_kind": "official", "site_policy": "robots_allowed(crawl-delay 120)", "retrieved_at": now,
      "license": "public-sector-information", "sources": [{"source_url": "https://jusmendoza.gob.ar/guia-judicial/", "site_policy": "robots_allowed", "source_kind": "official"}], "record_note": "hierarchy node"})
    ids.add("ar-m-scjm")
def lv(n):
    n = n.lower()
    if "cámara" in n or "camara" in n: return "appellate"
    if "paz" in n or "contravencional" in n: return "trial_limited"
    if "familia" in n: return "family"
    if "menores" in n or "juvenil" in n: return "juvenile"
    if "tributari" in n: return "tax"
    return "trial_general"
for f in sorted(glob.glob(f"{RAW}/*.html")):
    slug = os.path.basename(f)[:-5]
    if slug == "guia": continue
    raw = open(f, "rb").read(); L = [x.strip() for x in re.sub(r"<[^>]+>", "\n", html.unescape(raw.decode("utf-8", "ignore"))).split("\n") if x.strip()]
    src = f"https://jusmendoza.gob.ar/{slug}/"
    for i, l in enumerate(L):
        if not re.search(r"\s[-–]\s?[1-4]CJ$", l) or len(l) > 160: continue
        if i + 1 < len(L) and L[i + 1].startswith("Ubicación") is False and "@" not in " ".join(L[i + 1:i + 3]) and "Ubicación:" not in L[i + 1:i + 4]: pass
        j = i + 1; js = []
        while j < len(L) and j < i + 40 and not L[j].startswith("Ubicación"):
            if "@" in L[j] and j + 1 < len(L): js.append((L[j - 1], L[j + 1]))
            j += 1
        if j >= len(L) or not L[j].startswith("Ubicación"): continue
        adr = L[j + 1] if L[j].strip() == "Ubicación:" else L[j].split(":", 1)[1].strip()
        parts = [p.strip() for p in adr.split(" - ")]; city = parts[-2] if len(parts) >= 2 else None
        tel = next((x for x in L[j:j + 15] if re.fullmatch(r"0\d{9,10}", x)), None)
        name = re.sub(r"\s+", " ", l); cid = "ar-m-" + re.sub(r"[^a-z0-9]+", "-", norm(name))[:100].strip("-")
        if cid in ids or norm(name) in seen: continue
        ids.add(cid); seen.add(norm(name))
        courts.append({"court_id": cid, "record_type": "courthouse", "name": name, "name_local": name, "level": lv(name), "court_system": "state", "country_code": "AR",
          "subdivision": "AR-M", "jurisdiction": (re.search(r"([1-4])CJ$", name).group(1) + "ª Circunscripción Judicial"), "parent_court_id": "ar-m-scjm",
          "address": {"street": adr, "city": city, "postcode": None, "region": "Mendoza", "country": "Argentina"}, "geo": {"lat": None, "lon": None}, "phone": tel,
          "website": src, "wikidata": None, "place_ids": rmatch([city, slug.replace("-", " ")], "AR") if city else [], "source_url": src, "source_kind": "official",
          "site_policy": "robots_allowed(crawl-delay 120)", "retrieved_at": datetime.datetime.fromtimestamp(os.path.getmtime(f), datetime.UTC).isoformat(),
          "license": "public-sector-information", "source_sha256": hashlib.sha256(raw).hexdigest(),
          "sources": [{"source_url": src, "site_policy": "robots_allowed", "source_kind": "official"}], "record_note": "Guía Judicial Mendoza", "municipality": city})
        for nm, title in js:
            if not re.search(r"juez|jueza|presidente|vocal|conjuez", title, re.I) or "@" in nm: continue
            jid = f"{cid}-{re.sub(r'[^a-z0-9]+', '-', norm(nm)).strip('-')}"
            if jid in jids: continue
            jids.add(jid); judges.append({"judge_id": jid, "court_id": cid, "name": nm, "title": title.strip(), "position_type": "judge", "term_start": None, "term_end": None,
              "status": "sitting", "roster_url": src, "source_url": src, "site_policy": "robots_allowed", "retrieved_at": now, "needs_review": True,
              "extraction": "Guía Judicial Mendoza; name+title only", "license": "public-sector-information"})
for p, rs in ((CO, courts), (JO, judges)):
    with open(p, "a") as fh:
        for r in rs: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print("courts", len(courts), "placed", sum(bool(r["place_ids"]) for r in courts), "judges", len(judges))
