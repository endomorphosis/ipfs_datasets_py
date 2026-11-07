"""TT (ttlawcourts.org, robots allows these pages) court locations + Justices of Appeal/High Court judges;
BB (barbadoslawcourts.gov.bb, crawl-delay 10 respected) Magistrates' Court details table + magistrate names. No e-mails/phones of staff stored."""
import json, sys, re, datetime, hashlib, html
sys.path.insert(0, "/workspace/world_courts/scrapers/courts/intl")
from row_common import *
now = datetime.datetime.now(datetime.UTC).isoformat(); RAW = f"{ROOT}/rules/raw"
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def slug(s): return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")[:90]
def ch(cc, name, city, level, parent, src, raw, sub, street=None, phone=None, note=""):
    return {"court_id": f"{cc}-{slug(name)}", "record_type": "courthouse", "name": name, "name_local": None, "level": level, "court_system": "national", "country_code": cc.upper(),
      "subdivision": sub, "jurisdiction": city, "parent_court_id": parent, "address": {"street": street, "city": city, "postcode": None, "region": None,
      "country": {"tt": "Trinidad and Tobago", "bb": "Barbados"}[cc]}, "geo": {"lat": None, "lon": None}, "phone": phone, "website": None, "wikidata": None,
      "place_ids": rmatch([city], cc.upper()) if city else [], "source_url": src, "source_kind": "official", "site_policy": "robots_allowed", "retrieved_at": now,
      "license": "official judiciary website (facts)", "source_sha256": sha(raw), "sources": [{"source_url": src, "site_policy": "robots_allowed", "source_kind": "official"}],
      "record_note": note, "needs_review": False}
def jd(cc, court, name, title, ptype, src, raw):
    return {"judge_id": f"{cc}-{slug(court + ' ' + name)}", "court_id": court, "name": name, "title": title, "position_type": ptype, "term_start": None, "term_end": None,
      "status": "sitting", "roster_url": src, "source_url": src, "site_policy": "robots_allowed", "retrieved_at": now, "needs_review": False,
      "extraction": "official judiciary roster page (names and titles only)", "license": "official judiciary website (facts)", "source_sha256": sha(raw)}
def append(path, rows, key, extra_seen=()):
    old = [json.loads(l) for l in open(path)] if os.path.exists(path) else []; ids = {r[key] for r in old}
    nm = {norm(r.get("name") or "") for r in old} | set(extra_seen); new = [r for r in rows if r[key] not in ids and norm(r["name"]) not in nm]
    with open(path, "a") as f:
        for r in new: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(path.split("/")[-1], "+", len(new)); return old
import os
# ---- TT
S = "https://www.ttlawcourts.org/what-we-do/court-locations-contact-information"; P = f"{RAW}/tt/what-we-do_court-locations-contact-information.html"
TT_OSM = {"port of spain", "arima", "chaguanas", "couva", "san fernando", "mayaro", "rio claro", "princes town"}  # existing OSM magistrates' court rows
rows = []
for town, sub in [("Port of Spain","TT-POS"),("Arima","TT-ARI"),("Tunapuna","TT-TUP"),("Sangre Grande","TT-SGE"),("Chaguanas","TT-CHA"),("Couva","TT-CTT"),("San Fernando","TT-SFO"),
                  ("Mayaro","TT-MRC"),("Point Fortin","TT-PTF"),("Rio Claro","TT-MRC"),("Princes Town","TT-PRT"),("Siparia","TT-SIP"),("Scarborough","TT-TOB")]:
    if norm(town) in TT_OSM: continue
    rows.append(ch("tt", f"{town} District Court", town, "trial_limited", "tt-lower-court", S, P, sub, note="Magistracy district court (official locations page)"))
for nm, lvl, city, sub in [("Supreme Court of Trinidad and Tobago - Tobago (Civil and Criminal Divisions)", "trial_general", "Scarborough", "TT-TOB"),
                           ("Children Court, Tobago", "juvenile", "Scarborough", "TT-TOB"), ("Family Court, Tobago", "family", "Scarborough", "TT-TOB")]:
    rows.append(ch("tt", nm, city, lvl, "tt-high-court", S, P, sub, note="Tobago court listed on official locations page"))
append(f"{ROOT}/data/tt/tt_courthouses.jsonl", rows, "court_id")
J = []
for f, court, ptype in [("who-we-are_judges-court-appeal.html", "tt-court-of-appeal", "appellate"), ("who-we-are_high-court-judges.html", "tt-high-court", "trial")]:
    src = "https://www.ttlawcourts.org/who-we-are/" + f.split("_", 1)[1][:-5]; t = html.unescape(re.sub(r"<[^>]+>", "\n", open(f"{RAW}/tt/{f}", errors="ignore").read()))
    for l in t.split("\n"):
        l = l.strip()
        m = re.match(r"The Honourable (Chief Justice, Mr\. Justice |Justice |)(.+?)(,? J\.A\.( \(Ag\.\))?|, O\.R\.T\.T\.|\*)?$", l)
        if not m or len(m.group(2)) > 60: continue
        name = m.group(2).strip(" ,"); cj = "Chief" in m.group(1); ag = "(Ag.)" in (m.group(3) or "")
        title = "Chief Justice" if cj else ("Justice of Appeal" + (" (Acting)" if ag else "") if ptype == "appellate" else "Judge of the High Court")
        J.append(jd("tt", "tt-supreme-court" if cj else court, name, title, "chief" if cj else ptype, src, f"{RAW}/tt/{f}"))
append(f"{ROOT}/data/tt/tt_judges.jsonl", J, "judge_id")
# ---- BB
S = "https://www.barbadoslawcourts.gov.bb/judicial-system/the-magistrates-courts"; P = f"{RAW}/bb/judicial_systemthe_magistrates_courts.html"
BB = [("District 'A' Traffic Court", "Coleridge Street, Bridgetown", "Bridgetown", "BB-08", "trial_limited"),
      ("District 'A' Criminal Court No. 2", "Coleridge Street, Bridgetown", "Bridgetown", "BB-08", "trial_limited"),
      ("District 'A' Civil Court", "St. Matthias Court Complex", None, "BB-01", "trial_limited"),
      ("District 'A' Juvenile Court", "Roebuck Street, Bridgetown", "Bridgetown", "BB-08", "juvenile"),
      ("District 'A' Domestic Court", "St. Matthias Court Complex", None, "BB-01", "family"),
      ("Coroner's Court", "Roebuck Street, Bridgetown", "Bridgetown", "BB-08", "specialized"),
      ("District 'B' Magistrate's Court (Boarded Hall)", "Boarded Hall, St. George", None, "BB-03", "trial_limited"),
      ("District 'C' Magistrate's Court", "St. Matthias Court Complex", None, "BB-01", "trial_limited"),
      ("District 'E' Magistrate's Court (Holetown)", "Holetown, St. James", "Holetown", "BB-04", "trial_limited"),
      ("District 'F' Belleplaine Magistrate's Court", "Belleplaine, St. Andrew", "Belleplaine", "BB-02", "trial_limited")]
# Oistins (B), District D, District F (Tamarind Hall), St. Matthias already exist as OSM rows
append(f"{ROOT}/data/bb/bb_courthouses.jsonl", [ch("bb", n, c, l, "bb-lower-court", S, P, s, street=a, note="Magistrates' Court details table (official)") for n, a, c, s, l in BB], "court_id")
MAG = [("Douglas Frederick", "District 'A' (St. Michael) and Coroner's Court"), ("Laurie-Ann Smith-Bovell", "District 'B' (St. George)"),
       ("Christopher Birch", "District 'C' (St. John)"), ("Ian Weekes", "District 'D' (St. Thomas)"), ("Wanda Blair", "Districts 'E' and 'F'")]
append(f"{ROOT}/data/bb/bb_judges.jsonl", [dict(jd("bb", "bb-lower-court", n, f"Magistrate ({a})", "trial", S, P), needs_review=True) for n, a in MAG], "judge_id")
