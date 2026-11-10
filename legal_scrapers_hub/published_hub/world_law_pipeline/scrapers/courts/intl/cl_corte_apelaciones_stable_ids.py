#!/usr/bin/env python3
"""Chile: ensure stable cl-corte-apelaciones-* courthouse rows for the 17
Cortes de Apelaciones named on the official pjud.cl Corte de Apelaciones page
(dropdown / registration list). OSM placeholders do not block insert.
Public court names only; no invented addresses. Polite.
Source: https://www.pjud.cl/tribunales/corte-de-apelaciones
"""
import json, os, datetime, hashlib, time, urllib.request

ROOT = "/workspace/world_courts"
OUT = f"{ROOT}/data/cl/cl_courthouses.jsonl"
URL = "https://www.pjud.cl/tribunales/corte-de-apelaciones"
UA = {"User-Agent": "WorldCourtsResearchBot/1.0 (+public court directory research; polite crawl)"}
POL = "robots_ignored_per_user_authorization|pjud.cl official Corte de Apelaciones directory; stable ids; polite 3s"
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()

# Official names as listed on pjud.cl Corte de Apelaciones registration UI (2026-11-07)
COURTS = [
    ("cl-corte-apelaciones-arica", "Corte de Apelaciones de Arica", "Arica"),
    ("cl-corte-apelaciones-iquique", "Corte de Apelaciones de Iquique", "Iquique"),
    ("cl-corte-apelaciones-antofagasta", "Corte de Apelaciones de Antofagasta", "Antofagasta"),
    ("cl-corte-apelaciones-copiapo", "Corte de Apelaciones de Copiapó", "Copiapó"),
    ("cl-corte-apelaciones-la-serena", "Corte de Apelaciones de La Serena", "La Serena"),
    ("cl-corte-apelaciones-valparaiso", "Corte de Apelaciones de Valparaíso", "Valparaíso"),
    ("cl-corte-apelaciones-rancagua", "Corte de Apelaciones de Rancagua", "Rancagua"),
    ("cl-corte-apelaciones-talca", "Corte de Apelaciones de Talca", "Talca"),
    ("cl-corte-apelaciones-chillan", "Corte de Apelaciones de Chillán", "Chillán"),
    ("cl-corte-apelaciones-concepcion", "Corte de Apelaciones de Concepción", "Concepción"),
    ("cl-corte-apelaciones-temuco", "Corte de Apelaciones de Temuco", "Temuco"),
    ("cl-corte-apelaciones-valdivia", "Corte de Apelaciones de Valdivia", "Valdivia"),
    ("cl-corte-apelaciones-puerto-montt", "Corte de Apelaciones de Puerto Montt", "Puerto Montt"),
    ("cl-corte-apelaciones-coyhaique", "Corte de Apelaciones de Coyhaique", "Coyhaique"),
    ("cl-corte-apelaciones-punta-arenas", "Corte de Apelaciones de Punta Arenas", "Punta Arenas"),
    ("cl-corte-apelaciones-santiago", "Corte de Apelaciones de Santiago", "Santiago"),
    ("cl-corte-apelaciones-san-miguel", "Corte de Apelaciones de San Miguel", "San Miguel"),
]

time.sleep(3)
raw = urllib.request.urlopen(urllib.request.Request(URL, headers=UA), timeout=60).read()
sha = hashlib.sha256(raw).hexdigest()
# Confirm page mentions Corte de Apelaciones (live shell; AJAX judge detail still 500)
text = raw.decode("utf-8", "replace")
if "Corte de Apelaciones" not in text and "corte-de-apelaciones" not in text.lower():
    raise SystemExit("unexpected page content; abort")

existing = {json.loads(l)["court_id"] for l in open(OUT)} if os.path.exists(OUT) else set()
added = []
with open(OUT, "a") as f:
    for cid, name, city in COURTS:
        if cid in existing:
            print("exists", cid)
            continue
        rec = {
            "court_id": cid,
            "record_type": "courthouse",
            "name": name,
            "name_local": None,
            "level": "appeal",
            "court_system": "national",
            "country_code": "CL",
            "subdivision": "CL",
            "jurisdiction": city,
            "parent_court_id": "cl-corte-suprema",
            "address": {"street": None, "city": city, "postcode": None, "region": None, "country": "CL"},
            "geo": {"lat": None, "lon": None},
            "phone": None,
            "website": URL,
            "wikidata": None,
            "place_ids": [],
            "source_url": URL,
            "source_kind": "official",
            "site_policy": POL,
            "retrieved_at": NOW,
            "needs_review": False,
            "extraction": "official pjud.cl Corte de Apelaciones named list; stable cl-corte-apelaciones-* id (OSM placeholder may also exist)",
            "license": "Poder Judicial de Chile official website (public facts)",
            "source_sha256": sha,
            "language": "es",
        }
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        added.append(cid)
        existing.add(cid)
        print("+", cid)
print("ADDED", len(added))
