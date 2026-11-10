"""PH: RTC stations (seat + branch ranges) from OCA 'Updated Territorial Jurisdiction of the RTCs' (A.M. No. 24-08-10-SC, as of 27 Nov 2024), via Wayback snapshot
(oca.judiciary.gov.ph unreachable from the box). One courthouse row per RTC seat per judicial region; branch list in record_note."""
import json, sys, re, datetime, hashlib
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
RAW = f"{ROOT}/rules/raw/ph_sc"; OUT = f"{ROOT}/data/ph/ph_courthouses.jsonl"
SRC = "https://oca.judiciary.gov.ph/wp-content/uploads/Updated-Teritorial-Jurisdiction-as-of-November-27-2024.pdf"
WB = "https://web.archive.org/web/20251206055101/" + SRC
sha = hashlib.sha256(open(f"{RAW}/tj.pdf", "rb").read()).hexdigest()
rows = [json.loads(l) for l in open(OUT)]; ids = {r["court_id"] for r in rows}
t = open(f"{RAW}/tj.txt", encoding="utf-8").read().replace("\f", "\n").split("\n")
region = prov = None; new = []; nseat = 0; i = 0; seat = None; lvl1 = []
RG = r"^\s*((?:NATIONAL CAPITAL|FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|ELEVENTH|TWELFTH|THIRTEENTH)\s+JUDICIAL REGION|BANGSAMORO[A-Z ]*)"
now = datetime.datetime.now(datetime.UTC).isoformat()
def row(cid, name, level, city, note):
    if cid in ids: return
    ids.add(cid)
    new.append({"court_id": cid, "record_type": "courthouse", "name": name, "name_local": None, "level": level, "court_system": "national",
      "country_code": "PH", "subdivision": "PH", "jurisdiction": f"{region}; {prov}" if prov else region, "parent_court_id": None,
      "address": {"street": None, "city": city, "postcode": None, "region": prov, "country": "Philippines"}, "geo": {"lat": None, "lon": None}, "phone": None, "website": None,
      "wikidata": None, "place_ids": rmatch([city, re.sub(r"(?i)\s*city$|^city of\s+", "", city)], "PH") if city else [], "source_url": SRC, "source_kind": "official",
      "site_policy": "archived_copy(wayback);origin_unreachable", "retrieved_at": now, "license": "Supreme Court of the Philippines / OCA (public document)", "source_sha256": sha,
      "sources": [{"source_url": WB, "site_policy": "archived_copy(wayback)", "source_kind": "official"}], "record_note": note, "needs_review": city is None})
def slug(x): return re.sub(r"[^a-z0-9]+", "-", norm(x)).strip("-")[:100]
buf = ""
for l in t:
    s0 = l.strip()
    m = re.match(RG, l)
    if m: region = m.group(1).title(); prov = None; continue
    if re.fullmatch(r"[A-Z][A-Z .'Ñ-]{2,40}\d{0,4}", s0) and len(l) - len(l.lstrip()) > 20 and "|" not in s0: prov = re.sub(r"\d+$", "", s0).title(); continue
    m = re.match(r"^\s*\d+\.\s+(.*)", l)
    if m: buf = m.group(1); seat = None; mt = None; continue
    if buf is not None and buf and s0 and seat is None: buf += " " + s0
    if buf and seat is None:
        mm = re.search(r"seats? at\s+([A-Za-zÑñ][A-Za-zÑñ .'-]+?)(?:\s*\d+)?\s*(?:[–—,(]|over|$)", re.sub(r"\s+", " ", buf))
        if mm:
            seat = mm.group(1).strip(" .").title(); seat = re.sub(r"\s+(Province|And)$", "", seat); nseat += 1
            br = re.sub(r"(?<=[a-z)])\d{1,3}(?=[\s,])", "", re.sub(r"(?<=[\d)]),\d{1,3}(?=\s)", "", re.sub(r"\s+", " ", buf[:buf.find("seat")]))).replace(" with", "").strip(" ,")
            row("ph-rtc-" + slug(f"{region} {prov or ''} {seat}"), f"Regional Trial Court, {seat}", "trial_general", seat, f"RTC station; {br}"[:400]); buf = ""
            continue
    if seat is None: continue
    m1 = re.match(r"^(MTCC|MeTC|MTC)\s+(.+)$", s0); m2 = re.match(r"^(\d+(?:st|nd|rd|th))\s+(MCTC|SCC)$", s0)
    if m1:
        k = {"MTCC": "Municipal Trial Court in Cities", "MeTC": "Metropolitan Trial Court", "MTC": "Municipal Trial Court"}[m1.group(1)]; c = m1.group(2).strip()
        row("ph-" + m1.group(1).lower() + "-" + slug(f"{prov or region} {c}"), f"{k}, {c}", "trial_limited", c, f"first-level court under RTC {seat}"); mt = None
    elif m2: mt = [m2.group(1), m2.group(2), []]
    elif mt is not None and re.fullmatch(r"[A-Z][A-Za-zÑñ .'()-]{2,40}", s0): 
        mt[2].append(s0); nm = f"{mt[0]} Municipal Circuit Trial Court, {' – '.join(mt[2])}" if mt[1] == "MCTC" else f"{mt[0]} Shari'a Circuit Court, {mt[2][0]}"
        cid = "ph-" + mt[1].lower() + "-" + slug(f"{prov or region} {mt[0]} {seat}")
        if cid in ids: [r.update(name=nm, record_note=f"first-level court under RTC {seat}; seat municipality listed first") for r in new if r["court_id"] == cid]
        else: row(cid, nm, "trial_limited", mt[2][0], f"first-level court under RTC {seat}")
    elif not s0: pass
    else: mt = None
with open(OUT, "a") as f:
    for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("seats", nseat, "added", len(new), "placed", sum(bool(r["place_ids"]) for r in new))
for r in new[:4] + new[-3:]: print(" ", r["name"], "|", r["jurisdiction"], "|", r["record_note"][:90])
