#!/usr/bin/env python3
"""Bolivia: ensure stable bo-tdj-* courthouse rows for Chuquisaca, La Paz,
Cochabamba, Potosí from official TSJ directory
https://tsj.bo/institucion/tribunales-departamentales-justicia/
Skips only when the stable court_id already exists (OSM placeholders do not block).
Public address/phone/website facts only. Polite.
"""
import json, re, html, datetime, hashlib, urllib.request

ROOT = "/workspace/world_courts"
OUT = f"{ROOT}/data/bo/bo_courthouses.jsonl"
URL = "https://tsj.bo/institucion/tribunales-departamentales-justicia/"
UA = {"User-Agent": "WorldCourtsResearchBot/1.0 (+public court directory research; polite crawl)"}
POL = "robots_ignored_per_user_authorization|tsj.bo official TDJ directory; factual address/phone/website only|polite"
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()

CITY = {
    "CHUQUISACA": ("Sucre", "BO-H", "bo-tdj-chuquisaca", "https://tdjch.organojudicial.gob.bo/"),
    "LA PAZ": ("La Paz", "BO-L", "bo-tdj-la-paz", "https://lapaz.organojudicial.gob.bo/"),
    "COCHABAMBA": ("Cochabamba", "BO-C", "bo-tdj-cochabamba", "https://tdjcbba.organojudicial.gob.bo/"),
    "POTOSI": ("Potosí", "BO-P", "bo-tdj-potosi", "http://wtdjpts.organojudicial.gob.bo/"),
}

def main():
    raw = urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=60).read()
    sha = hashlib.sha256(raw).hexdigest()
    s = raw.decode("utf-8", "replace")
    s = re.sub(r"<style.*?</style>|<script.*?</script>", "", s, flags=re.S)
    t = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>', r" [A \1] ", s)
    t = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)))
    if "TRIBUNALES DEPARTAMENTALES DE JUSTICIA" in t:
        t = t[t.find("TRIBUNALES DEPARTAMENTALES DE JUSTICIA"):]
    if "Footer" in t:
        t = t[: t.find("Footer")]
    existing = {json.loads(l)["court_id"] for l in open(OUT)} if __import__("os").path.exists(OUT) else set()
    blocks = re.split(r"TRIBUNAL DEPARTAMENTAL DE JUSTICIA DE ", t)[1:]
    added = []
    for b in blocks:
        dep = next((k for k in CITY if b.upper().startswith(k)), None)
        if not dep:
            continue
        city, sub, cid, default_web = CITY[dep]
        if cid in existing:
            print("exists", cid)
            continue
        addr = re.search(r"Direcci[oó]n:\s*(.*?)\s*Tel[eé]fonos?:", b, re.I)
        tel = re.search(r"Tel[eé]fonos?:\s*(.*?)\s*(?:FAX|Fax|\[A|$)", b, re.I)
        webm = re.search(r"\[A (https?://[a-z0-9.-]*organojudicial\.gob\.bo/?)\]", b, re.I)
        web = webm.group(1) if webm else default_web
        name_dep = "Potosí" if dep == "POTOSI" else dep.title()
        rec = {
            "court_id": cid,
            "record_type": "courthouse",
            "name": f"Tribunal Departamental de Justicia de {name_dep}",
            "name_local": None,
            "level": "appellate",
            "court_system": "national",
            "country_code": "BO",
            "subdivision": sub,
            "jurisdiction": f"Departamento de {name_dep}",
            "parent_court_id": "bo-supreme-court",
            "address": {
                "street": addr.group(1).strip() if addr else None,
                "city": city,
                "postcode": None,
                "region": name_dep,
                "country": "BO",
            },
            "geo": {"lat": None, "lon": None},
            "phone": tel.group(1).strip() if tel else None,
            "website": web,
            "wikidata": None,
            "place_ids": [],
            "source_url": URL,
            "source_kind": "official",
            "site_policy": POL,
            "retrieved_at": NOW,
            "needs_review": False,
            "extraction": "official tsj.bo TDJ directory; stable bo-tdj-* id (OSM placeholder may also exist)",
            "license": "Tribunal Supremo de Justicia de Bolivia official website (public facts)",
            "source_sha256": sha,
            "language": "es",
        }
        added.append(rec)
        existing.add(cid)
        print("+", cid, rec["address"]["street"], rec["phone"], web)
    with open(OUT, "a") as f:
        for r in added:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("ADDED", len(added))

if __name__ == "__main__":
    main()
